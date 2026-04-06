"""Plan plugin — complex task planning, execution, and reflection.

Provides 5 tools:
- plan_task: decompose a complex task into multiple solution plans
- compare_solutions: compare plans by risk/complexity/outcome
- view_plan: visualize execution plan as a table
- execute_plan: run plan step-by-step with real tool execution
- reflect_and_revise: on failure, analyze cause and generate a revised plan

Hook: on_llm_call detects complex tasks (>= 3 tool calls) and suggests planning.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from py_code_agent.llm.litellm_provider import Message, MessageRole
from py_code_agent.plugins.hooks import hookimpl
from py_code_agent.tools.base import (
    BaseTool,
    ToolDefinition,
    ToolParameter,
    ToolParameterType,
    ToolResult,
)

logger = logging.getLogger(__name__)

# Import orchestrator components
try:
    from .plan_orchestrator import (
        AdvancedOrchestrator,
        OrchestratedTask,
        TaskPriority,
        TaskState,
        AdaptiveParallelism,
        OrchestratorMetrics,
        ResourceAllocation,
    )
    ORCHESTRATOR_AVAILABLE = True
except ImportError:
    ORCHESTRATOR_AVAILABLE = False
    ResourceAllocation = None
    logger.warning("Plan orchestrator not available, using legacy execution mode")

# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class SubTask:
    id: str
    title: str
    description: str
    status: Literal["pending", "running", "completed", "failed", "skipped"] = "pending"
    result: Optional[str] = None
    error: Optional[str] = None
    retry_count: int = 0
    dependencies: List[str] = field(default_factory=list)
    skill_context: str = ""  # skill workflow guidance to follow (Option B)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "retry_count": self.retry_count,
            "dependencies": self.dependencies,
            "skill_context": self.skill_context,
        }


@dataclass
class Plan:
    id: str
    name: str
    description: str
    approach: str = "alternative"  # "conservative" | "aggressive" | "alternative"
    risk_level: str = "medium"
    estimated_steps: int = 0
    subtasks: List[SubTask] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    status: Literal["draft", "approved", "executing", "completed", "failed", "revised"] = "draft"
    skill_context: str = ""  # skill workflow guidance from skill tool invocations (Option B)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "approach": self.approach,
            "risk_level": self.risk_level,
            "estimated_steps": len(self.subtasks),
            "subtasks": [s.to_dict() for s in self.subtasks],
            "created_at": self.created_at,
            "status": self.status,
            "skill_context": self.skill_context,
        }


@dataclass
class HeartbeatState:
    """Tracks heartbeat status for a running subtask (master→subagent)."""
    subtask_id: str
    last_heartbeat: float = field(default_factory=time.time)
    missed_count: int = 0
    alive: bool = True
    aborted: bool = False

    def ping(self) -> None:
        self.last_heartbeat = time.time()
        self.missed_count = 0

    def mark_missed(self) -> None:
        self.missed_count += 1

    def mark_dead(self) -> None:
        self.alive = False

    def mark_aborted(self) -> None:
        self.aborted = True
        self.alive = False

    def seconds_since_heartbeat(self) -> float:
        return time.time() - self.last_heartbeat


# ─────────────────────────────────────────────────────────────────────────────
# Prompt templates
# ─────────────────────────────────────────────────────────────────────────────

PLAN_GENERATION_PROMPT = """You are a task planning assistant. Given a user task, generate {num_plans} distinct solution approaches.

Task: {task}

{skill_context}For each approach, output a JSON object with:
- "name": short name for this approach (e.g. "Conservative", "Aggressive", "Alternative")
- "description": one-sentence description of the approach
- "approach": one of "conservative", "aggressive", or "alternative"
- "risk_level": "low", "medium", or "high"
- "estimated_steps": approximate number of steps
- "subtasks": array of subtasks, each with:
  - "title": short title (max 10 words, plain text only, no special characters)
  - "description": brief description of what to do (1-2 sentences, max 100 chars). Plain text only, NO parentheses, NO special JSON-like characters.

IMPORTANT:
- Keep description SHORT and SIMPLE (max 100 characters)
- Plain text only: no parentheses (), no quotes inside strings, no tool call syntax
- Subtask description is used as tool parameter — keep it short!

Return a JSON array of {num_plans} objects. No markdown, no explanation — pure JSON only.
"""

COMPARISON_PROMPT = """Compare these {num_plans} solution plans for the task and output a comparison table.

Task: {task}

{plans_text}

For each plan, evaluate:
- **Risk**: How likely is this to fail or cause issues?
- **Complexity**: How many steps/dependencies?
- **Outcome quality**: How good is the expected result?
- **Best for**: When is this approach ideal?

Then rank them: #1 (recommended), #2, #3.

Return a JSON object:
{{
  "rankings": [
    {{"rank": 1, "plan_id": "...", "reason": "..."}},
    ...
  ],
  "comparison_table": [
    {{"plan_id": "...", "risk": "...", "complexity": "...", "outcome": "...", "best_for": "..."}},
    ...
  ]
}}

Pure JSON only, no markdown.
"""

REFLECTION_PROMPT = """A subtask failed during plan execution.

Task: {task}
Plan: {plan_name}
Failed subtask: "{subtask_title}"
Error: {error}
Previous result: {previous_result}

Analyze why this failed and generate a revised approach that can succeed.

COMMON FAILURE PATTERNS — check these first:
1. **Missing dependency**: "command not found", "module not found", "No such file or directory"
   → Fix: install the missing tool/runtime with execute_bash, then retry
2. **Wrong tool used**: generic tool instead of specialized skill workflow
   → Fix: re-read the relevant skill content and follow its required workflow
3. **Skill workflow skipped**: used a shortcut instead of the correct steps
   → Fix: follow the skill's steps IN ORDER from the beginning
4. **Permission/environment issue**: sandbox restrictions, wrong path
   → Fix: use execute_bash to find available paths, adjust tool arguments
5. **Partial output**: some steps worked but result is wrong
   → Fix: identify the failing step, fix only that step, preserve successful work

After diagnosing, return a JSON object:
{{
  "diagnosis": "What went wrong and why — be specific about the root cause",
  "revised_description": "Revised subtask description with CONCRETE fix steps.
     Include exact commands to run (e.g. 'Run: execute_bash with install command').
     Do NOT just restate the original task — fix the failure first.",
  "alternative_tools": ["tool1", "tool2"] or null,
  "self_heal_steps": ["step1 (e.g. install dependency)", "step2 (e.g. retry)"] or null
}}

IMPORTANT: If the failure is a missing dependency, your revised_description MUST start
with the fix step (e.g. "1. Install the missing tool: execute_bash('pip install package')")
before retrying the original task. The subagent will execute your revised_description.

Pure JSON only, no markdown.
"""

MAX_RETRY = 3
MAX_CONCURRENT_AGENTS = 4  # max parallel sub-agents


# ─────────────────────────────────────────────────────────────────────────────
# Tools
# ─────────────────────────────────────────────────────────────────────────────


class AssessComplexityTool(BaseTool):
    """Assess task complexity - gatekeeper for all tasks.
    
    This tool forces the LLM to explicitly declare whether a task needs planning.
    It's NOT a programmatic check - it's a structured decision prompt.
    The LLM must output its own reasoning and decision.
    """

    def __init__(self, plugin: "PlanPlugin"):
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="assess_complexity",
            description="Assess if the current task requires planning. "
                        "MUST be called FIRST before executing ANY task. "
                        "You MUST explicitly state your decision at the END of reasoning: 'needs_planning: true' or 'needs_planning: false'",
            parameters=[
                ToolParameter(
                    name="task",
                    type=ToolParameterType.STRING,
                    description="The user's task to assess",
                    required=True,
                ),
                ToolParameter(
                    name="reasoning",
                    type=ToolParameterType.STRING,
                    description="Your reasoning for complexity assessment. "
                                "IMPORTANT: You MUST end your reasoning with 'needs_planning: true' or 'needs_planning: false'. "
                                "Example: 'This task requires multiple steps and file analysis... needs_planning: true'",
                    required=True,
                ),
            ],
        )

    async def execute(self, task: str, reasoning: str, **kwargs: Any) -> ToolResult:
        """Parse LLM's explicit complexity decision.
        
        Tool doesn't judge - parses LLM's explicit declaration.
        If LLM didn't explicitly state decision, return error to force re-assessment.
        """
        import re
        
        reasoning_lower = reasoning.lower()
        
        needs_planning = None
        
        patterns = [
            r"needs_planning:\s*(true|false|yes|no)",
            r"needs_planning\s*=\s*(true|false|yes|no)",
            r"planning\s*required:\s*(true|false|yes|no)",
            r"decision:\s*(plan|direct|true|false|yes|no)",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, reasoning_lower)
            if match:
                value = match.group(1).lower()
                if value in ("true", "yes", "plan"):
                    needs_planning = True
                elif value in ("false", "no", "direct"):
                    needs_planning = False
                break
        
        if needs_planning is None:
            return ToolResult(
                success=False,
                error="INVALID RESPONSE: You must explicitly state your decision at the END of reasoning. "
                      "Format: '... needs_planning: true' or '... needs_planning: false'. "
                      "Do NOT just explain - state your DECISION explicitly."
            )
        
        if needs_planning:
            return ToolResult(
                success=False,
                error=f"DECISION: needs_planning=true. You MUST call plan_task(task='{task[:40]}...', num_plans=2) NOW. "
                      f"This is mandatory. Do not execute any other tool before planning."
            )
        else:
            return ToolResult(
                success=True,
                data={"needs_planning": False, "task": task},
                summary=f"DECISION: needs_planning=false. You may proceed with direct execution."
            )


class PlanTaskTool(BaseTool):
    """Generate multiple solution plans for a complex task."""

    def __init__(self, plugin: "PlanPlugin"):
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="plan_task",
            description="Generate 2-3 distinct solution plans for a complex task. Each plan includes step-by-step subtasks. Call this when a task involves multiple steps, file changes, or unfamiliar code areas.",
            parameters=[
                ToolParameter(
                    name="task",
                    type=ToolParameterType.STRING,
                    description="The complex task to plan (e.g. 'rebuild the auth system', 'migrate database to postgres')",
                    required=True,
                ),
                ToolParameter(
                    name="num_plans",
                    type=ToolParameterType.INTEGER,
                    description="Number of plans to generate (default 2, max 4)",
                    required=False,
                ),
            ],
        )

    async def execute(self, task: str, num_plans: int = 2, **kwargs: Any) -> ToolResult:
        num_plans = min(max(num_plans, 1), 4)
        try:
            # OPTION B: Extract skill tool results from session messages
            # Subagent shares plugin/skill ecosystem with master — skill invocations
            # made before plan_task are available in the conversation history.
            skill_context_text = ""
            try:
                agent_ref = self._plugin._agent_ref
                if agent_ref is not None:
                    session = getattr(agent_ref, "session", None)
                    if session is not None:
                        for msg in session.messages:
                            content = msg.get("content", "")
                            if not content:
                                continue
                            role = msg.get("role", "")
                            # Check for skill tool results (TOOL messages with skill_ name)
                            tool_name = msg.get("name", "")
                            if role == "tool" and tool_name and "skill_" in tool_name:
                                try:
                                    import json
                                    data = json.loads(content)
                                    if isinstance(data, dict) and data.get("success"):
                                        skill_data = data.get("data", {})
                                        if isinstance(skill_data, dict) and "content" in skill_data:
                                            skill_name = skill_data.get("name", tool_name)
                                            skill_content = skill_data["content"]
                                            # Truncate to avoid token limits
                                            skill_context_text = (
                                                f"[Skill: {skill_name}]\n"
                                                f"{skill_content[:3000]}"
                                            )
                                            break
                                except (json.JSONDecodeError, KeyError, TypeError):
                                    pass
            except Exception:
                pass  # Non-fatal: continue without skill context

            skill_context_section = (
                f"IMPORTANT — Relevant skill workflow context:\n"
                f"{skill_context_text}\n\n"
                if skill_context_text else ""
            )
            messages = [
                Message(
                    role=MessageRole.USER,
                    content=PLAN_GENERATION_PROMPT.format(
                        task=task,
                        num_plans=num_plans,
                        skill_context=skill_context_section,
                    ),
                )
            ]
            llm = self._plugin._agent_ref.llm
            response = await llm.complete(messages, temperature=0.5)
            content = response.get("content", "")

            # Parse JSON
            plans = self._parse_json_array(content, task)
            if not plans:
                return ToolResult.fail(
                    f"Failed to generate plans. LLM response: {content[:200]}"
                )

            # Attach skill context to all plans so subtasks can reference it
            for p in plans:
                p.skill_context = skill_context_text

            stored = self._plugin._store_plans(plans)
            lines = [f"## Generated {len(stored)} Plans\n"]
            lines.append("")
            for p in stored:
                lines.append(f"**Plan {p.id[:8]}**: {p.name} ({p.approach}, risk={p.risk_level})")
                lines.append(f"  {p.description}")
                lines.append(f"  {len(p.subtasks)} subtasks")
                lines.append("")
            
            self._plugin._emit_heartbeat("generated",
                plan_id=stored[0].id if stored else "",
                num_plans=len(stored),
                plan_ids=[p.id for p in stored])

            summary = f"{len(stored)} plans generated. Use `compare_solutions` or `view_plan`."
            return ToolResult.ok(
                data={"plans": [p.to_dict() for p in stored], "count": len(stored)},
                summary=summary,
            )
        except Exception as e:
            logger.warning("[PlanPlugin] plan_task failed: %s", e)
            return ToolResult.fail(f"Plan generation failed: {e}")

    def _parse_json_array(self, content: str, task: str) -> List[Plan]:
        """Parse LLM JSON response into Plan objects."""
        import json

        # Try direct JSON parse first
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Try to extract JSON array from text
            match = re.search(r"\[[\s\S]*\]", text)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    return []
            else:
                return []

        plans = []
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            plan_id = uuid.uuid4().hex[:8]
            subtasks = []
            for i, st in enumerate(item.get("subtasks", []), 1):
                if isinstance(st, dict):
                    subtasks.append(
                        SubTask(
                            id=f"{plan_id}-{i}",
                            title=st.get("title", f"Step {i}")[:50],
                            description=st.get("description", ""),
                            dependencies=st.get("dependencies", []),
                        )
                    )
            plans.append(
                Plan(
                    id=plan_id,
                    name=item.get("name", f"Plan {plan_id}"),
                    description=item.get("description", ""),
                    approach=item.get("approach", "alternative"),
                    risk_level=item.get("risk_level", "medium"),
                    estimated_steps=item.get("estimated_steps", len(subtasks)),
                    subtasks=subtasks,
                )
            )
        return plans


class CompareSolutionsTool(BaseTool):
    """Compare multiple solution plans by risk, complexity, and outcome quality."""

    def __init__(self, plugin: "PlanPlugin"):
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="compare_solutions",
            description="Compare 2 or more plans by risk, complexity, and outcome quality. Shows a ranking table.",
            parameters=[
                ToolParameter(
                    name="plan_ids",
                    type=ToolParameterType.STRING,
                    description="Comma-separated plan IDs to compare (from plan_task output)",
                    required=True,
                ),
            ],
        )

    async def execute(self, plan_ids: str, **kwargs: Any) -> ToolResult:
        try:
            ids = [p.strip() for p in plan_ids.split(",")]
            plans = []
            for pid in ids:
                plan = self._plugin._plans.get(pid)
                if plan:
                    plans.append(plan)
            if len(plans) < 2:
                return ToolResult.fail(
                    f"Need at least 2 plans to compare, got: {len(plans)}. "
                    "Generate plans first with plan_task."
                )

            task_desc = " | ".join(p.description for p in plans)
            plans_text = "\n".join(
                f"Plan {p.id[:8]} ({p.approach}, risk={p.risk_level}): "
                + f"{p.description} | Steps: {', '.join(s.title for s in p.subtasks)}"
                for p in plans
            )

            messages = [
                Message(
                    role=MessageRole.USER,
                    content=COMPARISON_PROMPT.format(
                        task=task_desc, num_plans=len(plans), plans_text=plans_text
                    ),
                )
            ]
            llm = self._plugin._agent_ref.llm
            response = await llm.complete(messages, temperature=0.3)
            content = response.get("content", "")

            # Extract rankings
            rankings = []
            text = content.strip()
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)
            try:
                import json
                data = json.loads(text)
                rankings = data.get("rankings", [])
                table = data.get("comparison_table", [])
            except (json.JSONDecodeError, TypeError):
                rankings = []
                table = []

            lines = ["## Plan Comparison\n"]
            lines.append("| Rank | Plan | Risk | Complexity | Outcome | Best For |")
            lines.append("|------|------|------|------------|---------|----------|")
            for p in plans:
                rank_info = next(
                    (r for r in rankings if r.get("plan_id", "").startswith(p.id[:8])),
                    {},
                )
                rank = rank_info.get("rank", "?")
                table_info = next(
                    (t for t in table if t.get("plan_id", "").startswith(p.id[:8])),
                    {},
                )
                risk = table_info.get("risk", p.risk_level)
                complexity = table_info.get("complexity", f"{len(p.subtasks)} steps")
                outcome = table_info.get("outcome", "-")
                best_for = table_info.get("best_for", "-")
                rec = " ⭐" if rank == 1 else ""
                lines.append(
                    f"| {rank}{rec} | {p.name} | {risk} | {complexity} | {outcome} | {best_for} |"
                )
            lines.append("")
            lines.append("⭐ = recommended")

            summary = f"Compared {len(plans)} plans"
            return ToolResult.ok(
                data={
                    "plans": [p.to_dict() for p in plans],
                    "rankings": rankings,
                    "comparison_table": table,
                },
                summary=summary,
            )
        except Exception as e:
            logger.warning("[PlanPlugin] compare_solutions failed: %s", e)
            return ToolResult.fail(f"Plan comparison failed: {e}")


class ViewPlanTool(BaseTool):
    """Visualize a plan as an execution table."""

    def __init__(self, plugin: "PlanPlugin"):
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="view_plan",
            description="Show a plan's execution table with subtask IDs, titles, descriptions, and status. Use after plan_task to review what will be executed.",
            parameters=[
                ToolParameter(
                    name="plan_id",
                    type=ToolParameterType.STRING,
                    description="Plan ID from plan_task output",
                    required=True,
                ),
            ],
        )

    async def execute(self, plan_id: str, **kwargs: Any) -> ToolResult:
        plan = self._plugin._plans.get(plan_id)
        if not plan:
            return ToolResult.fail(
                f"Plan '{plan_id}' not found. Available: {list(self._plugin._plans.keys())}"
            )

        lines = [
            f"## Plan: {plan.name} ({plan.id[:8]})",
            f"**Approach**: {plan.approach} | **Risk**: {plan.risk_level} | **Status**: {plan.status}",
            f"**Description**: {plan.description}",
            "",
            "| # | Subtask | Status | Dependencies |",
            "|---|---------|--------|---------------|",
        ]
        for i, st in enumerate(plan.subtasks, 1):
            deps = ", ".join(st.dependencies) if st.dependencies else "-"
            status_icon = {"pending": "⏳", "running": "🔄", "completed": "✅", "failed": "❌", "skipped": "⏭️"}.get(st.status, "?")
            lines.append(f"| {i} | **{st.title}** | {status_icon} {st.status} | {deps} |")
        lines.append("")
        lines.append(f"Execute with: `execute_plan(plan_id='{plan_id}')`")

        return ToolResult.ok(
            data=plan.to_dict(),
            summary=f"Plan '{plan.name}' — {len(plan.subtasks)} subtasks, status={plan.status}",
        )


class ExecutePlanTool(BaseTool):
    """Execute a plan using parallel sub-agents. Each independent subtask
    runs as a separate Agent instance in parallel (up to MAX_CONCURRENT_AGENTS).
    Subtasks with dependencies run after their dependencies complete.
    Failed subtasks trigger reflection + retry (max MAX_RETRY times)."""

    def __init__(self, plugin: "PlanPlugin"):
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="execute_plan",
            description="Execute a plan by running subtasks in parallel using sub-agents. Independent subtasks run simultaneously (up to 4 at a time). Subtasks with dependencies wait for their dependencies to complete. Failed subtasks trigger reflection and automatic retry (max 3 times).",
            parameters=[
                ToolParameter(
                    name="plan_id",
                    type=ToolParameterType.STRING,
                    description="Plan ID from plan_task output",
                    required=True,
                ),
                ToolParameter(
                    name="max_agents",
                    type=ToolParameterType.INTEGER,
                    description=f"Max parallel sub-agents (default {MAX_CONCURRENT_AGENTS}, max {MAX_CONCURRENT_AGENTS})",
                    required=False,
                ),
            ],
        )

    async def execute(
        self, plan_id: str, max_agents: int = MAX_CONCURRENT_AGENTS, use_orchestrator: bool = True, **kwargs: Any
    ) -> ToolResult:
        """Execute a plan using either legacy mode or advanced orchestrator.
        
        Args:
            plan_id: Plan ID from plan_task output
            max_agents: Max parallel agents (legacy mode)
            use_orchestrator: Whether to use AdvancedOrchestrator (default: True)
        """
        plan = self._plugin._plans.get(plan_id)
        if not plan:
            return ToolResult.fail(
                f"Plan '{plan_id}' not found. Available: {list(self._plugin._plans.keys())}"
            )

        if not plan.subtasks:
            return ToolResult.ok(
                data={"plan": plan.to_dict(), "completed": 0, "failed": 0},
                summary=f"Plan '{plan.name}' has no subtasks",
            )

        self._plugin._emit_heartbeat("execute_started",
            plan_id=plan.id,
            plan_name=plan.name,
            num_subtasks=len(plan.subtasks))
        
        start_time = time.time()

        # Check if orchestrator is available and requested
        # TEMP: Disable AdvancedOrchestrator due to skill_context parameter issue
        if False and use_orchestrator and self._plugin._orchestrator is not None:
            logger.info(f"Using AdvancedOrchestrator for plan '{plan.name}'")
            result = await self._execute_with_orchestrator(plan)
        else:
            logger.info(f"Using legacy execution mode for plan '{plan.name}'")
            result = await self._execute_legacy(plan, max_agents)

        duration_s = time.time() - start_time
        
        self._plugin._emit_heartbeat("execute_completed",
            plan_id=plan.id,
            plan_name=plan.name,
            success=result.data.get("completed", 0) > 0 if result.data else False,
            completed=result.data.get("completed", 0) if result.data else 0,
            failed=result.data.get("failed", 0) if result.data else 0,
            duration_s=round(duration_s, 1))
        
        return result
    
    async def _execute_with_orchestrator(self, plan: Plan) -> ToolResult:
        """Execute plan using AdvancedOrchestrator."""
        orchestrator = self._plugin._orchestrator
        
        # Start orchestrator
        await orchestrator.start()
        
        try:
            # Convert plan subtasks to OrchestratedTasks
            task_map: Dict[str, OrchestratedTask] = {}
            
            for subtask in plan.subtasks:
                orch_task = OrchestratedTask(
                    id=subtask.id,
                    name=subtask.title,
                    description=subtask.description,
                    priority=TaskPriority.NORMAL,
                    state=TaskState.PENDING,
                    dependencies=subtask.dependencies,
                    resources=ResourceAllocation(
                        timeout_seconds=300,  # 5 minute default
                    ),
                    skill_context=subtask.skill_context,
                )
                task_map[subtask.id] = orch_task
            
            # Submit all tasks to orchestrator
            for task in task_map.values():
                await orchestrator.submit_task(task)
            
            # Wait for all tasks to complete (with timeout)
            all_completed = False
            timeout_seconds = 3600  # 1 hour max
            start_wait = time.time()
            
            while not all_completed and (time.time() - start_wait) < timeout_seconds:
                # Check if all tasks are done
                all_done = all(
                    task.state in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED)
                    for task in task_map.values()
                )
                
                if all_done:
                    all_completed = True
                    break
                    
                await asyncio.sleep(1.0)
            
            # Collect results
            completed_count = sum(1 for t in task_map.values() if t.state == TaskState.COMPLETED)
            failed_count = sum(1 for t in task_map.values() if t.state == TaskState.FAILED)
            
            # Update plan status
            plan.status = "completed" if failed_count == 0 else "failed"
            
            # Generate report
            report_lines = [f"## Executing: {plan.name} (orchestrator mode)\n"]
            
            for subtask in plan.subtasks:
                orch_task = task_map.get(subtask.id)
                if orch_task:
                    if orch_task.state == TaskState.COMPLETED:
                        report_lines.append(f"  ✅ {subtask.title}: DONE")
                        subtask.status = "completed"
                        subtask.result = str(orch_task.result) if orch_task.result else None
                    elif orch_task.state == TaskState.FAILED:
                        report_lines.append(f"  ❌ {subtask.title}: FAILED - {orch_task.error}")
                        subtask.status = "failed"
                        subtask.error = str(orch_task.error) if orch_task.error else None
                    else:
                        report_lines.append(f"  ⏳ {subtask.title}: {orch_task.state.name}")
                        subtask.status = orch_task.state.name.lower()
            
            report_lines.append(f"\n## Summary: {completed_count} completed, {failed_count} failed")
            
            # Get orchestrator metrics
            metrics_report = orchestrator.get_metrics_report()
            report_lines.append(f"\n### Orchestrator Metrics:")
            report_lines.append(f"- Adaptive Workers: {metrics_report['adaptive_workers']}")
            report_lines.append(f"- Active Tasks: {metrics_report['active_tasks']}")
            report_lines.append(f"- Queued Tasks: {metrics_report['queued_tasks']}")
            
            return ToolResult.ok(
                data={
                    "plan": plan.to_dict(),
                    "completed": completed_count,
                    "failed": failed_count,
                    "metrics": metrics_report,
                },
                summary="\n".join(report_lines),
            )
            
        finally:
            # Stop orchestrator
            await orchestrator.stop()
    
    async def _execute_legacy(self, plan: Plan, max_agents: int) -> ToolResult:
        """Execute plan using legacy mode (original implementation)."""
        # ... existing legacy implementation ...
        max_agents = min(max(max_agents, 1), MAX_CONCURRENT_AGENTS)
        master_agent = self._plugin._agent_ref

        # Build dependency graph: subtask_id -> list of dependent subtask ids
        completed_ids: set[str] = set()
        done_count = 0
        failed_count = 0
        report_lines = [f"## Executing: {plan.name} (parallel, max {max_agents} agents)\n"]

        while True:
            # Find all ready subtasks (deps satisfied, not yet run)
            ready = [
                st for st in plan.subtasks
                if st.status == "pending"
                and all(dep in completed_ids for dep in st.dependencies)
            ]

            if not ready:
                # Check if we're done or deadlocked
                pending = [st for st in plan.subtasks if st.status == "pending"]
                if not pending:
                    break  # all done
                # Deadlock: dependencies can't be satisfied
                for st in pending:
                    st.status = "failed"
                    st.error = "Deadlock: unsatisfiable dependencies"
                    failed_count += 1
                break

            # Limit batch size
            batch = ready[:max_agents]

            # Build subtask title line
            if len(batch) == 1:
                report_lines.append(f"### ▶ {batch[0].title} (sequential)")
            else:
                names = ", ".join(st.title[:20] for st in batch)
                report_lines.append(f"### ▶ Parallel batch ({len(batch)}): {names}")

            for st in batch:
                st.status = "running"
                # OPTION B: Inject skill workflow context into subtask so _run_subtask
                # can pass it to the subagent — subagent shares plugin/skill ecosystem
                if plan.skill_context and not st.skill_context:
                    st.skill_context = plan.skill_context

            # Run batch in parallel
            batch_results = await asyncio.gather(
                *[
                    self._plugin._run_subtask(st, master_agent)
                    for st in batch
                ],
                return_exceptions=True,
            )

            # Process results
            for st, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    st.status = "failed"
                    st.error = str(result)
                    failed_count += 1
                    report_lines.append(f"  ❌ {st.title}: FAILED - {result}")
                else:
                    st.status = "completed"
                    st.result = result
                    completed_ids.add(st.id)
                    done_count += 1
                    report_lines.append(f"  ✅ {st.title}: DONE")

        # Summary
        report_lines.append(f"\n## Summary: {done_count} completed, {failed_count} failed")
        plan.status = "completed" if failed_count == 0 else "failed"

        return ToolResult.ok(
            data={
                "plan": plan.to_dict(),
                "completed": done_count,
                "failed": failed_count,
            },
            summary="\n".join(report_lines),
        )

        if not plan.subtasks:
            return ToolResult.ok(
                data={"plan": plan.to_dict(), "completed": 0, "failed": 0},
                summary=f"Plan '{plan.name}' has no subtasks",
            )

        max_agents = min(max(max_agents, 1), MAX_CONCURRENT_AGENTS)
        master_agent = self._plugin._agent_ref

        # Build dependency graph: subtask_id -> list of dependent subtask ids
        completed_ids: set[str] = set()
        done_count = 0
        failed_count = 0
        report_lines = [f"## Executing: {plan.name} (parallel, max {max_agents} agents)\n"]

        while True:
            # Find all ready subtasks (deps satisfied, not yet run)
            ready = [
                st for st in plan.subtasks
                if st.status == "pending"
                and all(dep in completed_ids for dep in st.dependencies)
            ]

            if not ready:
                # Check if we're done or deadlocked
                pending = [st for st in plan.subtasks if st.status == "pending"]
                if not pending:
                    break  # all done
                # Deadlock: dependencies can't be satisfied
                for st in pending:
                    st.status = "failed"
                    st.error = "Deadlock: unsatisfiable dependencies"
                    failed_count += 1
                break

            # Limit batch size
            batch = ready[:max_agents]

            # Build subtask title line
            if len(batch) == 1:
                report_lines.append(f"### ▶ {batch[0].title} (sequential)")
            else:
                names = ", ".join(st.title[:20] for st in batch)
                report_lines.append(f"### ▶ Parallel batch ({len(batch)}): {names}")

            for st in batch:
                st.status = "running"
                # OPTION B: Inject skill workflow context into subtask so _run_subtask
                # can pass it to the subagent — subagent shares plugin/skill ecosystem
                if plan.skill_context and not st.skill_context:
                    st.skill_context = plan.skill_context

            # Run batch in parallel
            batch_results = await asyncio.gather(
                *[
                    self._plugin._run_subtask(st, master_agent)
                    for st in batch
                ],
                return_exceptions=True,
            )

            for st, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    st.status = "failed"
                    st.error = str(result)
                    failed_count += 1
                    report_lines.append(f"  ❌ {st.title}: {str(result)[:100]}")
                else:
                    ok, val = result
                    if ok:
                        st.status = "completed"
                        st.result = val[:300] if val else "Done"
                        completed_ids.add(st.id)
                        done_count += 1
                        report_lines.append(f"  ✅ {st.title}: {val[:80]}")
                    else:
                        # Retry with reflection
                        revised_ok, revised_val = await self._plugin._reflect_and_retry(
                            st, plan, master_agent
                        )
                        if revised_ok:
                            st.status = "completed"
                            st.result = f"(revised) {revised_val[:300]}"
                            completed_ids.add(st.id)
                            done_count += 1
                            report_lines.append(f"  ✅ {st.title} (revised): {revised_val[:80]}")
                        else:
                            st.status = "failed"
                            st.error = val
                            failed_count += 1
                            completed_ids.add(st.id)  # mark done so dependents can run
                            report_lines.append(
                                f"  ❌ {st.title} (gave up after {MAX_RETRY} retries): {val[:80]}"
                            )

            report_lines.append("")

        plan.status = "completed" if failed_count == 0 else "failed"
        report_lines.append(
            f"## Summary: {done_count} ✅ | {failed_count} ❌ | "
            f"{len([st for st in plan.subtasks if st.status == 'skipped'])} ⏭️"
        )

        return ToolResult.ok(
            data={
                "plan": plan.to_dict(),
                "completed": done_count,
                "failed": failed_count,
                "parallel_batches": _count_batches(plan),
                "summary": report_lines,
            },
            summary=f"{plan.name}: {done_count} done, {failed_count} failed",
        )


class ReflectOnFailureTool(BaseTool):
    """Manually trigger reflection on a failed subtask and see the diagnosis."""

    def __init__(self, plugin: "PlanPlugin"):
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="reflect_on_failure",
            description="Manually analyze a failed subtask — get diagnosis and revised approach. Shows what went wrong and how to fix it.",
            parameters=[
                ToolParameter(
                    name="plan_id",
                    type=ToolParameterType.STRING,
                    description="Plan ID",
                    required=True,
                ),
                ToolParameter(
                    name="subtask_id",
                    type=ToolParameterType.STRING,
                    description="Subtask ID (format: plan-id-N)",
                    required=True,
                ),
            ],
        )

    async def execute(self, plan_id: str, subtask_id: str, **kwargs: Any) -> ToolResult:
        plan = self._plugin._plans.get(plan_id)
        if not plan:
            return ToolResult.fail(f"Plan '{plan_id}' not found")
        subtask = next((s for s in plan.subtasks if s.id == subtask_id), None)
        if not subtask:
            return ToolResult.fail(f"Subtask '{subtask_id}' not found in plan")

        diagnosis, revised = await self._plugin._reflect(subtask, plan)
        lines = [
            f"## Reflection: {subtask.title}",
            f"**Error**: {subtask.error or 'Unknown'}",
            "",
            f"**Diagnosis**: {diagnosis}",
            "",
            f"**Revised approach**: {revised}",
        ]
        return ToolResult.ok(
            data={"diagnosis": diagnosis, "revised_description": revised},
            summary=diagnosis[:100],
        )


# ─────────────────────────────────────────────────────────────────────────────
# PlanPlugin
# ─────────────────────────────────────────────────────────────────────────────


class PlanPlugin:
    """Plugin for complex task planning, execution, and reflection.

    Dependencies:
        - ContextPlugin (file:context): provides context tool for subtask coordination
    
    Hooks:
        on_llm_call: detects complex tasks (>= 3 tool calls) → suggests planning

    Tools:
        plan_task, compare_solutions, view_plan, execute_plan, reflect_on_failure
        (Context tool delegated to ContextPlugin)
    """

    def __init__(self):
        self._agent_ref: Optional[Any] = None
        self._plans: Dict[str, Plan] = {}
        self._executing: bool = False
        self._current_plan_id: Optional[str] = None
        self.PLUGIN_NAME = "plan"
        self.PLUGIN_ID = f"plan-{uuid.uuid4().hex[:6]}"
        
        # Initialize advanced orchestrator if available
        self._orchestrator: Optional[AdvancedOrchestrator] = None
        if ORCHESTRATOR_AVAILABLE:
            try:
                self._orchestrator = AdvancedOrchestrator(max_workers=MAX_CONCURRENT_AGENTS)
                logger.info("Advanced orchestrator initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize orchestrator: {e}")

    def set_agent(self, agent: Any) -> None:
        """Receive agent reference from PluginManager."""
        self._agent_ref = agent

    # ── Hooks ────────────────────────────────────────────────────────────────

    @hookimpl
    def register_tools(self) -> List[BaseTool]:
        return [
            AssessComplexityTool(self),  # Gatekeeper - MUST be called first
            PlanTaskTool(self),
            CompareSolutionsTool(self),
            ViewPlanTool(self),
            ExecutePlanTool(self),
            ReflectOnFailureTool(self),
        ]

    @hookimpl
    def enhance_tool_error_priority(self) -> int:
        return 10

    @hookimpl
    def on_llm_call(
        self, messages: List[Dict[str, str]], tools: List[Dict[str, Any]]
    ) -> None:
        pass

    @hookimpl
    def get_system_prompt(self) -> str:
        """Inject MANDATORY planning rules into the agent's system prompt."""
        return """<plugin_depends>file:context</plugin_depends>
        
## CRITICAL: YOUR FIRST ACTION IS FIXED

When you receive a task, you MUST call this tool FIRST:

### assess_complexity(task="...", reasoning="...")

This tool determines if you need to plan. That's it. No exceptions.

**If you call ANY other tool first - You have violated the protocol.**
**If you skip this tool - The system will reject your execution.**

---

### The Protocol (you cannot deviate):

1. RECEIVE TASK -> 2. assess_complexity -> 3. plan_task (if needed) -> 4. execute

```
User: "do something"
-> FIRST: assess_complexity(task="do something", reasoning="...")
-> THEN:  based on result, either plan_task or direct execution
```

### What If You Violate:
- Your tool calls will be rejected
- You'll waste turns
- Task will fail

### What If You Follow:
- assess_complexity returns needs_planning=true -> call plan_task
- AFTER plan_task: You MUST call execute_plan(plan_id) to execute the plan
- DO NOT skip execute_plan and go directly to task_done
- Clean, efficient, correct

---

### Tool Reference:
- assess_complexity(task, reasoning) <- MANDATORY FIRST
- plan_task(task, num_plans) <- if needs_planning=true
- execute_plan(plan_id) <- execute plan
- view_plan(plan_id) <- review plan
- compare_solutions(plan_ids) <- compare
- reflect_on_failure(subtask_id) <- fix failures
- context(...) <- For context sharing, see ContextPlugin guidelines

**Remember: assess_complexity is your GATEKEEPER. Without it, nothing else is valid.**"""


    @hookimpl
    def enhance_tool_error(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        error_info: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Enhance plan_task and execute_plan errors with diagnosis and fix suggestions."""
        error_msg = error_info.get("error", "")
        msg_lower = error_msg.lower()

        if tool_name == "plan_task":
            if "json" in msg_lower or "parse" in msg_lower:
                return {
                    "error_type": "plan_task_json_error",
                    "diagnosis": "plan_task failed to parse LLM response as JSON. The planner returned non-JSON output.",
                    "fix_suggestions": [
                        "Retry with simpler task description",
                        "Reduce num_plans to 2 to simplify the response",
                        "Include example format in the task description",
                    ],
                    "confidence": 0.95,
                }

        if tool_name == "execute_plan":
            if "deadlock" in msg_lower:
                return {
                    "error_type": "plan_deadlock",
                    "diagnosis": "Plan execution deadlocked — subtask dependencies form a cycle or can't be satisfied.",
                    "fix_suggestions": [
                        "Use `view_plan(plan_id)` to check subtask dependencies",
                        "Use `reflect_on_failure(subtask_id)` to diagnose specific failures",
                        "Break circular dependencies by removing or reordering subtasks",
                    ],
                    "confidence": 1.0,
                }
            if "heartbeat timeout" in msg_lower:
                return {
                    "error_type": "subtask_timeout",
                    "diagnosis": "A subtask timed out — subagent did not respond within the heartbeat window.",
                    "fix_suggestions": [
                        "The subtask may be waiting for external input (e.g., user confirmation, network response)",
                        "Break long-running subtasks into smaller parallel steps",
                        "Use `reflect_on_failure(subtask_id)` to retry with shorter timeout",
                    ],
                    "confidence": 1.0,
                }
            if "plan" in msg_lower and "not found" in msg_lower:
                plan_ids = list(self._plans.keys())
                return {
                    "error_type": "plan_not_found",
                    "diagnosis": f"Plan not found. Available plans: {', '.join(plan_ids[:5]) or 'none'}",
                    "fix_suggestions": [
                        f"Use `view_plan('{plan_ids[0] if plan_ids else 'plan_id'}')` to see available plans",
                        "Run `plan_task` first to create a plan",
                    ],
                    "confidence": 1.0,
                }

        return None

    # ── Internal helpers ───────────────────────────────────────────────────

    def _store_plans(self, plans: List[Plan]) -> List[Plan]:
        for plan in plans:
            self._plans[plan.id] = plan
        return plans

    async def _reflect(self, subtask: SubTask, plan: Plan) -> tuple[str, str]:
        """Call LLM for failure diagnosis and revised approach."""
        if self._agent_ref is None:
            return "Agent not available", subtask.description

        messages = [
            Message(
                role=MessageRole.USER,
                content=REFLECTION_PROMPT.format(
                    task=plan.description,
                    plan_name=plan.name,
                    subtask_title=subtask.title,
                    error=subtask.error or "Unknown error",
                    previous_result=subtask.result or "No result",
                ),
            )
        ]
        try:
            response = await self._agent_ref.llm.complete(messages, temperature=0.4)
            content = response.get("content", "")
            text = content.strip()
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)
            import json
            data = json.loads(text)
            diagnosis = data.get("diagnosis", "Unable to diagnose")
            revised = data.get("revised_description", subtask.description)
            return diagnosis, revised
        except Exception:
            return "Reflection failed (LLM error)", subtask.description

    async def _run_subtask(self, subtask: SubTask, agent: Any) -> tuple[bool, str]:
        """Run a subtask using Agent.clone().
        
        Creates a true sub-agent that inherits the full plugin ecosystem from master.
        Keeps context tool but disables assess_complexity/plan_task.
        """
        subagent = agent.clone(
            modifications={
                "disabled_tools": ["assess_complexity", "plan_task", "compare_solutions", "execute_plan", "view_plan", "reflect_on_failure"],
                "system_prompt_additions": f"""
## SUBTASK: {subtask.title}

### Task Description
{subtask.description}

### WORKFLOW (in order):
1. Do your analysis work
2. Store findings: context(action="write", key="...", value="simple text only")
3. Mark task complete: task_done(original_task="...", expected_output="...")

### JSON FORMAT RULES (MUST FOLLOW):
- All string values must be plain text, NOT containing tool call syntax
- Do NOT include parentheses, equals signs, or quotes inside string values
- String values should describe results, not contain code

GOOD: task_done(original_task="Analyze config", expected_output="Found 3 config files")
BAD: task_done(original_task="Analyze config", expected_output="使用 context(action='write'...)")

### WRONG OUTPUTS (NEVER DO THESE):
- task_done(original_task="X", expected_output="使用 context(action='write'...)")
- task_done(original_task="X", expected_output="context(action='write'...)")
- Any string containing: context(, task_done(, 'action=', 'key=', 'value='
""",
            }
        )

        all_results: List[str] = []
        
        self._emit_heartbeat("subtask_started",
            plan_id=self._current_plan_id or "",
            subtask_id=subtask.id,
            subtask_title=subtask.title)
        
        try:
            async for event in subagent.run(subtask.description):
                if event.type.name == "TOOL_START":
                    self._emit_heartbeat("tool_started",
                        plan_id=self._current_plan_id or "",
                        subtask_id=subtask.id,
                        tool_name=event.data.get("name", ""))
                elif event.type.name == "TOOL_END":
                    success = event.data.get("success", False)
                    self._emit_heartbeat("tool_completed",
                        plan_id=self._current_plan_id or "",
                        subtask_id=subtask.id,
                        success=success)
                elif event.type.name == "CONTENT":
                    all_results.append(event.data.get("content", ""))
                elif event.type.name == "END":
                    break
        except Exception as e:
            self._emit_heartbeat("subtask_failed",
                plan_id=self._current_plan_id or "",
                subtask_id=subtask.id,
                error=str(e))
            return False, f"Subagent error: {str(e)}"

        final_text = "\n".join(all_results[:10]).strip() if all_results else "Completed"
        
        self._emit_heartbeat("subtask_completed",
            plan_id=self._current_plan_id or "",
            subtask_id=subtask.id,
            subtask_title=subtask.title,
            success=True)
        
        return True, final_text

    def _route_heartbeat(self, event_type: str, **kwargs) -> None:
        """Forward a heartbeat event to HeartbeatPlugin if loaded."""
        if self._agent_ref is None:
            return
        try:
            pm = getattr(self._agent_ref, "plugin_manager", None)
            if pm is None:
                return
            hb_plugin = pm.get_plugin("heartbeat")
            if hb_plugin is None:
                return
            hb_plugin._append(event_type, **kwargs)
        except Exception:
            pass

    def _emit_heartbeat(self, event: str, **kwargs) -> None:
        """Emit unified plugin heartbeat event to HeartbeatPlugin."""
        if self._agent_ref is None:
            return
        try:
            pm = getattr(self._agent_ref, "plugin_manager", None)
            if pm is None:
                return
            event_data = {
                "plugin_name": self.PLUGIN_NAME,
                "plugin_id": self.PLUGIN_ID,
                **kwargs,
            }
            pm.call_on_plugin_heartbeat(event=event, data=event_data)
        except Exception:
            pass

    def _get_heartbeat_config(self, agent: Any) -> tuple[int, int]:
        """Extract (interval, timeout) from agent config. Defaults (30, 90) if not set."""
        try:
            hb = getattr(agent, "config", None)
            if hb and hasattr(hb, "heartbeat"):
                h = hb.heartbeat
                enabled = getattr(h, "enabled", True) if h else True
                if not enabled:
                    return 0, 0
                interval = getattr(h, "interval", 30)
                timeout = getattr(h, "timeout", 90)
                return int(interval), int(timeout)
        except Exception:
            pass
        return 30, 90

    def _build_tool_defs(self, agent: Any) -> List[Dict[str, Any]]:
        tool_defs: List[Dict[str, Any]] = []
        for tool in getattr(agent, "tools", {}).values():
            d = tool.definition
            params = [
                {
                    "name": p.name,
                    "description": p.description,
                    "type": str(p.type).replace("ToolParameterType.", "").lower(),
                    "required": p.required,
                }
                for p in d.parameters
            ]
            tool_defs.append({
                "type": "function",
                "function": {
                    "name": d.name,
                    "description": d.description,
                    "parameters": {
                        "type": "object",
                        "properties": {p["name"]: p for p in params},
                        "required": [p["name"] for p in params if p["required"]],
                    },
                },
            })
        return tool_defs

    def _parse_react_response(self, content: str) -> tuple[str, str, list]:
        """Parse ReAct-style response into Thought, Action, and tool_calls.
        
        Returns:
            (thought, action, tool_calls): thought is the reasoning,
            action is either a tool call (parsed from Action) or final answer,
            tool_calls is a list of tool call dicts if action is a tool call
        """
        thought = ""
        action = ""
        tool_calls = []
        
        # Parse Thought
        thought_match = content.split("Thought:")
        if len(thought_match) > 1:
            thought_part = thought_match[1].split("Action:")[0] if "Action:" in thought_match[1] else thought_match[1]
            thought = thought_part.strip()
        
        # Parse Action
        action_match = content.split("Action:")
        if len(action_match) > 1:
            action_part = action_match[1].split("Observation:")[0] if "Observation:" in action_match[1] else action_match[1]
            action = action_part.strip()
            
            # Check if action is a tool call (starts with [ or contains function name pattern)
            if action.startswith("[") or ("(" in action and ")" in action):
                # Try to parse as tool call
                try:
                    import json
                    if action.startswith("["):
                        parsed = json.loads(action)
                        # Transform parsed tool calls to expected format with "function" key
                        def transform_tool_call(tc):
                            if "function" in tc:
                                return tc
                            # Transform flat format to function format
                            return {
                                "id": tc.get("id", f"call_{hash(str(tc)) % 1000000}"),
                                "type": "function",
                                "function": {
                                    "name": tc.get("name", ""),
                                    "arguments": tc.get("arguments", "{}")
                                }
                            }
                        if isinstance(parsed, list):
                            tool_calls = [transform_tool_call(tc) for tc in parsed]
                        else:
                            tool_calls = [transform_tool_call(parsed)]
                    else:
                        # Simple function call parsing: func_name(args)
                        func_name = action.split("(")[0].strip()
                        args_str = action.split("(")[1].rsplit(")", 1)[0]
                        try:
                            args = json.loads("{" + args_str + "}") if args_str else {}
                        except:
                            args = {"_raw": args_str}
                        tool_calls = [{
                            "id": f"call_{hash(action) % 1000000}",
                            "type": "function",
                            "function": {
                                "name": func_name,
                                "arguments": json.dumps(args)
                            }
                        }]
                except Exception:
                    # If parsing fails, treat as final answer
                    tool_calls = []
        
        return thought, action, tool_calls

    async def _reflect_and_retry(
        self, subtask: SubTask, plan: Plan, agent: Any
    ) -> tuple[bool, str]:
        """Reflect on failure, revise subtask, retry up to MAX_RETRY times."""
        for attempt in range(1, MAX_RETRY + 1):
            subtask.retry_count = attempt
            logger.info(
                "[PlanPlugin] Retry %d/%d for subtask %s",
                attempt, MAX_RETRY, subtask.id
            )
            
            self._emit_heartbeat("subtask_retry",
                plan_id=plan.id,
                subtask_id=subtask.id,
                subtask_title=subtask.title,
                attempt=attempt,
                max_retries=MAX_RETRY)

            diagnosis, revised_desc = await self._reflect(subtask, plan)
            subtask.description = revised_desc

            success, result = await self._run_subtask(subtask, agent)
            if success:
                return True, result

            if attempt == MAX_RETRY:
                return False, result

            subtask.error = result

        return False, "Max retries exceeded"

    @hookimpl
    def on_agent_start(self, input: str) -> None:
        """Clear stale plans from previous sessions."""
        # Keep plans but mark draft ones as expired
        for plan in self._plans.values():
            if plan.status == "draft":
                plan.status = "draft"  # keep draft
        self._executing = False

    @hookimpl
    def on_agent_end(self) -> None:
        """Clean up execution state."""
        self._executing = False


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _count_batches(plan: Plan) -> int:
    """Count the number of parallel execution batches for a plan."""
    completed_ids: set[str] = set()
    batch_count = 0
    while True:
        ready = [
            st for st in plan.subtasks
            if st.status == "pending"
            and all(dep in completed_ids for dep in st.dependencies)
        ]
        if not ready:
            break
        batch_count += 1
        for st in ready:
            completed_ids.add(st.id)
            st.status = "completed"  # remove from future ready sets
    # Restore all to pending for actual execution
    for st in plan.subtasks:
        st.status = "pending"
    return batch_count

