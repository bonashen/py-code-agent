"""Sub-Agent Plugin — parallel background agent execution."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from py_code_agent.plugins.hooks import hookimpl
from py_code_agent.tools.base import (
    BaseTool,
    ToolDefinition,
    ToolParameter,
    ToolParameterType,
    ToolResult,
)

from py_code_agent_omo.plugins.category_router import CategoryRouterPlugin


@dataclass
class SubAgentTask:
    id: str
    category: str
    description: str
    prompt: str
    status: str = "pending"
    result: str = ""
    error: str = ""
    session_id: str = ""
    started_at: Optional[float] = None
    completed_at: Optional[float] = None


class SubAgentPlugin:
    """Background agent execution with category-based model routing.

    Leverages Agent.clone() from the host to spawn sub-agents that inherit
    the full plugin ecosystem. Each sub-agent runs with a category-resolved model.
    """

    MAX_CONCURRENT = 4
    DEFAULT_TIMEOUT = 300

    def __init__(self) -> None:
        self._agent_ref: Any = None
        self._tasks: Dict[str, SubAgentTask] = {}
        self._running_count = 0
        self._category_router: Optional[CategoryRouterPlugin] = None

    def set_agent(self, agent: Any) -> None:
        self._agent_ref = agent

    def _find_category_router(self) -> Optional[CategoryRouterPlugin]:
        if self._category_router:
            return self._category_router
        if not self._agent_ref:
            return None
        pm = getattr(self._agent_ref, "plugin_manager", None)
        if not pm:
            return None
        for name in pm.loaded_plugins:
            plugin = pm.pm.get_plugin(name)
            if plugin and isinstance(plugin, CategoryRouterPlugin):
                self._category_router = plugin
                return plugin
        return None

    @hookimpl
    def register_tools(self) -> List[BaseTool]:
        return [
            TaskTool(self),
            BackgroundOutputTool(self),
            BackgroundCancelTool(self),
            BackgroundListTool(self),
        ]

    @hookimpl
    def get_system_prompt(self) -> str:
        return """## Background Agent Execution

Use the `task` tool to delegate work to specialized sub-agents:

```python
task(category="visual-engineering", description="Redesign sidebar", prompt="...", run_in_background=True)
task(category="quick", description="Fix typo", prompt="...", run_in_background=False)
task(subagent_type="explore", description="Find auth patterns", prompt="...", run_in_background=True)
```

Rules:
- Fire 2-5 agents in parallel for non-trivial tasks
- Use `background_output(task_id)` to collect results
- Use `background_cancel(task_id)` to stop running tasks
- Sub-agents inherit the full plugin ecosystem from master
- Max 4 concurrent agents at a time"""

    async def spawn_task(self, task: SubAgentTask) -> None:
        task.status = "running"
        task.started_at = time.time()
        task.session_id = f"omo_{uuid.uuid4().hex[:8]}"
        self._running_count += 1

        try:
            router = self._find_category_router()
            if router:
                routing = router.route(task.category)
            else:
                routing = {"model": "openai/gpt-5.4-mini"}

            modifications = {
                "disabled_tools": self._get_disabled_tools(),
                "system_prompt_additions": self._build_subagent_prompt(task),
            }
            subagent = self._agent_ref.clone(modifications=modifications)

            model = routing.get("model", "openai/gpt-5.4-mini")
            subagent.llm = self._create_llm_provider(model, routing.get("variant"))

            results: List[str] = []
            async for event in subagent.run(task.prompt):
                if event.type.name == "CONTENT":
                    results.append(event.data.get("content", ""))
                elif event.type.name == "END":
                    break

            task.status = "completed"
            task.result = "\n".join(results)
            task.completed_at = time.time()

        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            task.completed_at = time.time()
        finally:
            self._running_count -= 1

    def _get_disabled_tools(self) -> List[str]:
        return [
            "task",
            "background_output",
            "background_cancel",
            "background_list",
        ]

    def _build_subagent_prompt(self, task: SubAgentTask) -> str:
        return (
            f"## SUBTASK: {task.description}\n\n"
            f"Category: {task.category}\n"
            f"Task ID: {task.id}\n\n"
            f"Execute this task and return results via task_done()."
        )

    def _create_llm_provider(self, model: str, variant: str | None = None) -> Any:
        from py_code_agent.llm.litellm_provider import LiteLLMProvider

        provider = LiteLLMProvider(model=model)
        variant_settings = {
            "default": 0.3,
            "high": 0.5,
            "xhigh": 0.7,
            "max": 0.9,
        }
        provider.temperature = variant_settings.get(variant or "default", 0.3)
        return provider


class TaskTool(BaseTool):
    def __init__(self, plugin: SubAgentPlugin) -> None:
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="task",
            description=(
                "Delegate work to a specialized sub-agent. Supports background execution "
                "for parallel work. Use category (visual-engineering, quick, ultrabrain, deep) "
                "for model routing, or subagent_type (oracle, librarian, explore) for specialized agents."
            ),
            parameters=[
                ToolParameter(
                    name="category",
                    type=ToolParameterType.STRING,
                    description="Task category for model routing",
                    required=False,
                ),
                ToolParameter(
                    name="subagent_type",
                    type=ToolParameterType.STRING,
                    description="Specialized agent type (oracle, librarian, explore)",
                    required=False,
                ),
                ToolParameter(
                    name="description",
                    type=ToolParameterType.STRING,
                    description="Short task description (3-5 words)",
                    required=True,
                ),
                ToolParameter(
                    name="prompt",
                    type=ToolParameterType.STRING,
                    description="Full detailed prompt for the agent",
                    required=True,
                ),
                ToolParameter(
                    name="run_in_background",
                    type=ToolParameterType.BOOLEAN,
                    description="Run asynchronously (default: true for parallel work)",
                    required=False,
                    default=True,
                ),
                ToolParameter(
                    name="load_skills",
                    type=ToolParameterType.ARRAY,
                    description="Skill names to inject",
                    required=False,
                ),
                ToolParameter(
                    name="session_id",
                    type=ToolParameterType.STRING,
                    description="Existing session to continue",
                    required=False,
                ),
            ],
        )

    async def execute(
        self,
        description: str,
        prompt: str,
        category: str = "",
        subagent_type: str = "",
        run_in_background: bool = True,
        load_skills: Optional[List[str]] = None,
        session_id: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        task_category = category or subagent_type or "unspecified-low"
        task_id = f"bg_{uuid.uuid4().hex[:8]}"
        task = SubAgentTask(
            id=task_id,
            category=task_category,
            description=description,
            prompt=prompt,
        )
        if session_id:
            task.session_id = session_id

        self._plugin._tasks[task_id] = task

        if run_in_background:
            asyncio.create_task(self._plugin.spawn_task(task))
            return ToolResult.ok(
                data={
                    "task_id": task_id,
                    "session_id": task.session_id,
                    "status": "running",
                },
                summary=f"Launched background task: {task_id} ({description})",
            )
        else:
            await self._plugin.spawn_task(task)
            if task.status == "completed":
                return ToolResult.ok(
                    data={"task_id": task_id, "result": task.result},
                    summary=task.result[:200],
                )
            return ToolResult.fail(f"Task failed: {task.error}")


class BackgroundOutputTool(BaseTool):
    def __init__(self, plugin: SubAgentPlugin) -> None:
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="background_output",
            description="Get output from a background task.",
            parameters=[
                ToolParameter(
                    name="task_id",
                    type=ToolParameterType.STRING,
                    description="Task ID to get output from",
                    required=True,
                ),
                ToolParameter(
                    name="block",
                    type=ToolParameterType.BOOLEAN,
                    description="Wait for completion",
                    required=False,
                    default=False,
                ),
                ToolParameter(
                    name="timeout",
                    type=ToolParameterType.INTEGER,
                    description="Max wait time in seconds",
                    required=False,
                    default=60,
                ),
            ],
        )

    async def execute(
        self,
        task_id: str,
        block: bool = False,
        timeout: int = 60,
        **kwargs: Any,
    ) -> ToolResult:
        task = self._plugin._tasks.get(task_id)
        if not task:
            return ToolResult.fail(f"Task not found: {task_id}")

        if block and task.status == "running":
            start = time.time()
            while task.status == "running" and (time.time() - start) < timeout:
                await asyncio.sleep(0.5)

        if task.status == "completed":
            duration = (
                task.completed_at - task.started_at if task.completed_at and task.started_at else 0
            )
            return ToolResult.ok(
                data={
                    "task_id": task_id,
                    "status": task.status,
                    "result": task.result,
                    "duration": duration,
                },
                summary=f"Task {task_id} completed: {task.result[:200]}",
            )
        elif task.status == "failed":
            return ToolResult.fail(f"Task {task_id} failed: {task.error}")
        else:
            return ToolResult.ok(
                data={"task_id": task_id, "status": task.status},
                summary=f"Task {task_id} still running",
            )


class BackgroundCancelTool(BaseTool):
    def __init__(self, plugin: SubAgentPlugin) -> None:
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="background_cancel",
            description="Cancel a running background task.",
            parameters=[
                ToolParameter(
                    name="task_id",
                    type=ToolParameterType.STRING,
                    description="Task ID to cancel",
                    required=True,
                ),
            ],
        )

    async def execute(self, task_id: str, **kwargs: Any) -> ToolResult:
        task = self._plugin._tasks.get(task_id)
        if not task:
            return ToolResult.fail(f"Task not found: {task_id}")
        if task.status == "running":
            task.status = "failed"
            task.error = "Cancelled by user"
            return ToolResult.ok(
                data={"task_id": task_id, "status": "cancelled"},
                summary=f"Cancelled task {task_id}",
            )
        return ToolResult.ok(
            data={"task_id": task_id, "status": task.status},
            summary=f"Task {task_id} already {task.status}",
        )


class BackgroundListTool(BaseTool):
    def __init__(self, plugin: SubAgentPlugin) -> None:
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="background_list",
            description="List all background tasks with their status.",
            parameters=[],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        tasks = self._plugin._tasks
        if not tasks:
            return ToolResult.ok(data={"tasks": []}, summary="No background tasks")

        lines = ["## Background Tasks\n"]
        lines.append("| Task ID | Category | Description | Status |")
        lines.append("|---------|----------|-------------|--------|")
        for tid, t in tasks.items():
            lines.append(f"| {tid[:12]} | {t.category} | {t.description[:30]} | {t.status} |")

        task_data = {
            tid: {
                "category": t.category,
                "status": t.status,
                "description": t.description,
            }
            for tid, t in tasks.items()
        }
        return ToolResult.ok(data={"tasks": task_data}, summary=f"{len(tasks)} background tasks")
