# SDD: py-code-agent-omo — Third-Party OMO Plugin Collection

> **Status**: Draft  
> **Date**: 2026-04-02  
> **Author**: Sisyphus  
> **Scope**: Design a standalone PyPI package that brings Oh My OpenCode capabilities to Py Code Agent as a third-party plugin collection

---

## 1. Problem Statement

Py Code Agent has a mature plugin system (pluggy-based, 5-layer self-healing, entry-point discovery). But its built-in plugins lack OMO's defining capabilities:

| Missing Capability | Impact |
|---|---|
| **Multi-model orchestration** | Single model does everything; no task-type routing |
| **Parallel sub-agents** | All work is sequential; no background delegation |
| **Intent classification** | Agent executes literally without understanding user intent |
| **Discipline enforcement** | No mechanism to prevent agent from quitting halfway |
| **Specialized agent roles** | One agent for all tasks; no role-based delegation |
| **Category-based model routing** | No mapping from task domain to optimal model |

**Goal**: Package these as a **standalone third-party plugin collection** — zero core modifications, installed via `pip`, discovered via entry points.

---

## 2. Design Principles

| Principle | Rationale |
|---|---|
| **Zero core changes** | No modifications to `py-code-agent` source; only uses public plugin APIs |
| **Entry-point distribution** | Installable via `pip install py-code-agent-omo`; auto-discovered |
| **Progressive enhancement** | Each plugin works independently; combined = full OMO experience |
| **Config-driven** | All behavior controlled by `~/.config/py-code-agent/omo.yaml` |
| **Leverage host APIs** | Uses `Agent.clone()`, `ContextPlugin`, `HeartbeatPlugin`, LiteLLM via `agent.llm` |
| **Self-healing inherits** | Py Code Agent's Layer 1-4 auto-repair protects all OMO plugins automatically |

---

## 3. Package Architecture

### 3.1 Distribution Model

```
┌──────────────────────────────────────────────────────────────┐
│  Py Code Agent (host)                                        │
│  - PluginManager (entry-point discovery)                     │
│  - pluggy hook system (ToolHooks + AgentHooks)               │
│  - Agent.clone() for sub-agent spawning                      │
│  - LiteLLMProvider for LLM calls                             │
│  - ContextPlugin, HeartbeatPlugin (built-in)                 │
└──────────────────────────┬───────────────────────────────────┘
                           │ entry points
                           │  (py_code_agent.plugins)
┌──────────────────────────▼───────────────────────────────────┐
│  py-code-agent-omo (third-party PyPI package)                │
│                                                              │
│  py_code_agent_omo/                                          │
│  ├── __init__.py          # Package init                    │
│  ├── config.py            # OMO config loader (YAML)        │
│  ├── agents/              # Agent prompt definitions        │
│  │   ├── oracle.py                                         │
│  │   ├── librarian.py                                      │
│  │   ├── explore.py                                        │
│  │   └── frontend_engineer.py                              │
│  ├── plugins/             # Plugin classes                  │
│  │   ├── intent_gate.py   # IntentGatePlugin               │
│  │   ├── category_router.py # CategoryRouterPlugin         │
│  │   ├── subagent.py      # SubAgentPlugin                 │
│  │   ├── discipline.py    # DisciplinePlugin               │
│  │   ├── comment_checker.py # CommentCheckerPlugin         │
│  │   └── think_mode.py    # ThinkModePlugin                │
│  └── tools/               # Shared tool utilities           │
│       └── base.py                                           │
│                                                              │
│  pyproject.toml           # Entry point registration        │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 Entry Point Registration

**`pyproject.toml`**:

```toml
[project]
name = "py-code-agent-omo"
version = "0.1.0"
description = "Oh My OpenCode plugin collection for Py Code Agent"
requires-python = ">=3.10"
dependencies = [
    "py-code-agent>=0.1.0",
    "pyyaml>=6.0",
    "pydantic>=2.0",
]

[project.entry-points."py_code_agent.plugins"]
intent-gate = "py_code_agent_omo.plugins.intent_gate"
category-router = "py_code_agent_omo.plugins.category_router"
subagent = "py_code_agent_omo.plugins.subagent"
discipline = "py_code_agent_omo.plugins.discipline"
comment-checker = "py_code_agent_omo.plugins.comment_checker"
think-mode = "py_code_agent_omo.plugins.think_mode"
```

### 3.3 How Py Code Agent Discovers OMO Plugins

The host's `PluginManager._load_from_entry_points()` automatically finds OMO:

```python
# In py-code-agent's PluginManager (existing code):
eps = entry_points().select(group="py_code_agent.plugins")
for ep in eps:
    self._load_entry_point(ep)  # OMO plugins loaded here
```

**No changes needed to Py Code Agent.**

---

## 4. Plugin Specifications

### 4.1 IntentGatePlugin

**File**: `py_code_agent_omo/plugins/intent_gate.py`

**Purpose**: Classify user intent before execution.

**Tools**:

| Tool | Parameters | Returns |
|---|---|---|
| `classify_intent` | `task: str` | `{intent: str, confidence: float, recommended_action: str}` |

**Hooks**:

| Hook | Behavior |
|---|---|
| `on_agent_start(input)` | Classify intent → store in ContextPlugin for other plugins |
| `get_system_prompt()` | Inject intent-aware execution rules |

**Implementation**:

```python
"""Intent Gate Plugin — classifies user intent before execution.

Dependencies:
    - file:context (uses context tool to share intent classification)
"""

from py_code_agent.plugins.hooks import hookimpl
from py_code_agent.tools.base import BaseTool, ToolDefinition, ToolParameter, ToolParameterType, ToolResult

INTENT_PROMPT = """Given this user task, classify its intent:

Task: {task}

Categories:
- research: "explain X", "how does Y work" → explore → synthesize → answer
- implementation: "implement X", "add Y", "create Z" → plan → delegate → execute
- investigation: "look into X", "check Y" → explore → report findings
- fix: "X is broken", "error Y" → diagnose → fix minimally
- open-ended: "refactor", "improve" → assess → propose → wait for confirmation

Return JSON: {{"intent": "...", "confidence": 0.0-1.0, "recommended_action": "..."}}"""


class IntentGatePlugin:
    def __init__(self):
        self._agent_ref = None
        self._current_intent = None

    def set_agent(self, agent):
        self._agent_ref = agent

    @hookimpl
    def register_tools(self):
        return [ClassifyIntentTool(self)]

    @hookimpl
    def on_agent_start(self, input: str) -> None:
        self._current_intent = self._classify(input)
        # Share with other OMO plugins via ContextPlugin
        if self._agent_ref:
            pm = getattr(self._agent_ref, "plugin_manager", None)
            if pm:
                ctx_plugin = pm.pm.get_plugin("file:context")
                if ctx_plugin:
                    ctx_plugin.write("current_intent", str(self._current_intent))

    @hookimpl
    def get_system_prompt(self) -> str:
        return """## Intent-Aware Execution

Your current task intent has been classified. Follow the recommended approach:
- Research → Explore first, synthesize findings, then answer
- Implementation → Plan before coding, delegate to specialists
- Investigation → Gather evidence, report findings
- Fix → Diagnose root cause, fix minimally
- Open-ended → Assess current state, propose approach, wait for confirmation"""

    def _classify(self, task: str) -> dict:
        # Use agent's LLM to classify
        if not self._agent_ref:
            return {"intent": "open-ended", "confidence": 0.0, "recommended_action": "assess first"}
        # ... LLM call via self._agent_ref.llm
        return {"intent": "implementation", "confidence": 0.9, "recommended_action": "plan → delegate"}


class ClassifyIntentTool(BaseTool):
    def __init__(self, plugin: IntentGatePlugin):
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="classify_intent",
            description="Classify the intent of a task. Returns intent type, confidence, and recommended action.",
            parameters=[
                ToolParameter(name="task", type=ToolParameterType.STRING, description="Task to classify", required=True),
            ],
        )

    async def execute(self, task: str, **kwargs) -> ToolResult:
        result = self._plugin._classify(task)
        return ToolResult.ok(data=result, summary=f"Intent: {result['intent']} (confidence: {result['confidence']})")
```

---

### 4.2 CategoryRouterPlugin

**File**: `py_code_agent_omo/plugins/category_router.py`

**Purpose**: Map task categories to optimal models. The core of multi-model orchestration.

**Config** (loaded from `~/.config/py-code-agent/omo.yaml`):

```yaml
category_router:
  enabled: true
  categories:
    visual-engineering:
      model: "google/gemini-3.1-pro"
      variant: "high"
    ultrabrain:
      model: "openai/gpt-5.4"
      variant: "xhigh"
    deep:
      model: "anthropic/claude-opus-4-6"
    quick:
      model: "openai/gpt-5.4-mini"
    artistry:
      model: "anthropic/claude-sonnet-4.6"
    unspecified-high:
      model: "anthropic/claude-opus-4.6"
    unspecified-low:
      model: "openai/gpt-5.4-mini"
    writing:
      model: "anthropic/claude-sonnet-4.6"
  agents:
    oracle:
      model: "openai/gpt-5.4"
      variant: "high"
    librarian:
      model: "anthropic/claude-sonnet-4.6"
    explore:
      model: "xai/grok-code-fast-1"
    frontend-engineer:
      model: "google/gemini-3.1-pro"
  provider_fallbacks:
    anthropic: ["openai", "google"]
    openai: ["anthropic", "google"]
```

**Tools**:

| Tool | Parameters | Returns |
|---|---|---|
| `route_task` | `category: str, task: str` | `{model: str, variant: str, provider: str}` |
| `list_categories` | — | Available categories with model assignments |
| `set_category_model` | `category: str, model: str` | Confirmation |

**Implementation**:

```python
"""Category Router Plugin — maps task categories to optimal models.

Dependencies:
    - file:context (reads intent classification from IntentGatePlugin)
"""

from py_code_agent.plugins.hooks import hookimpl
from py_code_agent.tools.base import BaseTool, ToolDefinition, ToolParameter, ToolParameterType, ToolResult

# Default category → model mapping
DEFAULT_CATEGORIES = {
    "visual-engineering": {"model": "google/gemini-3.1-pro", "variant": "high"},
    "ultrabrain": {"model": "openai/gpt-5.4", "variant": "xhigh"},
    "deep": {"model": "anthropic/claude-opus-4.6"},
    "quick": {"model": "openai/gpt-5.4-mini"},
    "artistry": {"model": "anthropic/claude-sonnet-4.6"},
    "unspecified-high": {"model": "anthropic/claude-opus-4.6"},
    "unspecified-low": {"model": "openai/gpt-5.4-mini"},
    "writing": {"model": "anthropic/claude-sonnet-4.6"},
}

DEFAULT_AGENTS = {
    "oracle": {"model": "openai/gpt-5.4", "variant": "high"},
    "librarian": {"model": "anthropic/claude-sonnet-4.6"},
    "explore": {"model": "xai/grok-code-fast-1"},
    "frontend-engineer": {"model": "google/gemini-3.1-pro"},
}


class CategoryRouterPlugin:
    def __init__(self):
        self._agent_ref = None
        self._categories = dict(DEFAULT_CATEGORIES)
        self._agents = dict(DEFAULT_AGENTS)
        self._fallbacks = {
            "anthropic": ["openai", "google"],
            "openai": ["anthropic", "google"],
        }
        self._load_config()

    def set_agent(self, agent):
        self._agent_ref = agent

    def _load_config(self):
        """Load OMO config from ~/.config/py-code-agent/omo.yaml"""
        import yaml
        from pathlib import Path
        
        config_paths = [
            Path(".py-code-agent/omo.yaml"),
            Path.home() / ".config" / "py-code-agent" / "omo.yaml",
        ]
        for p in config_paths:
            if p.exists():
                try:
                    with open(p) as f:
                        config = yaml.safe_load(f)
                    cr = config.get("category_router", {})
                    if cr.get("categories"):
                        self._categories.update(cr["categories"])
                    if cr.get("agents"):
                        self._agents.update(cr["agents"])
                    if cr.get("provider_fallbacks"):
                        self._fallbacks.update(cr["provider_fallbacks"])
                except Exception:
                    pass
                break

    def route(self, category: str) -> dict:
        """Resolve category → model assignment."""
        if category in self._categories:
            return self._categories[category]
        # Fallback to unspecified
        if category in ("visual", "frontend", "ui"):
            return self._categories.get("visual-engineering")
        return self._categories.get("unspecified-low", {"model": "openai/gpt-5.4-mini"})

    def resolve_agent(self, agent_name: str) -> dict:
        """Resolve agent name → model assignment."""
        return self._agents.get(agent_name, self._agents.get("librarian"))

    def resolve_with_fallback(self, model: str) -> str:
        """If primary model unavailable, try fallback providers."""
        provider = model.split("/")[0] if "/" in model else "openai"
        fallbacks = self._fallbacks.get(provider, [])
        # In production, check actual provider availability
        return model

    @hookimpl
    def register_tools(self):
        return [
            RouteTaskTool(self),
            ListCategoriesTool(self),
            SetCategoryModelTool(self),
        ]

    @hookimpl
    def get_system_prompt(self) -> str:
        cats = "\n".join(f"- `{cat}` → `{cfg['model']}`" for cat, cfg in self._categories.items())
        return f"""## Category-Based Model Routing

When delegating tasks, use the appropriate category. Each category maps to an optimal model:

{cats}

Categories are resolved automatically. You specify the category; the system picks the model."""


class RouteTaskTool(BaseTool):
    def __init__(self, plugin: CategoryRouterPlugin):
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="route_task",
            description="Resolve a task category to the optimal model. Returns model name, variant, and provider.",
            parameters=[
                ToolParameter(name="category", type=ToolParameterType.STRING, description="Task category (e.g., 'visual-engineering', 'quick', 'ultrabrain')", required=True),
                ToolParameter(name="task", type=ToolParameterType.STRING, description="Task description for context", required=False),
            ],
        )

    async def execute(self, category: str, task: str = "", **kwargs) -> ToolResult:
        routing = self._plugin.route(category)
        model = self._plugin.resolve_with_fallback(routing["model"])
        return ToolResult.ok(
            data={"model": model, "variant": routing.get("variant", "default"), "provider": model.split("/")[0]},
            summary=f"Routed '{category}' → {model}",
        )


class ListCategoriesTool(BaseTool):
    def __init__(self, plugin: CategoryRouterPlugin):
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="list_categories",
            description="List all available task categories with their model assignments.",
            parameters=[],
        )

    async def execute(self, **kwargs) -> ToolResult:
        lines = ["## Available Categories\n"]
        for cat, cfg in self._plugin._categories.items():
            lines.append(f"- **{cat}** → `{cfg['model']}` (variant: {cfg.get('variant', 'default')})")
        return ToolResult.ok(data={"categories": self._plugin._categories}, summary="\n".join(lines))


class SetCategoryModelTool(BaseTool):
    def __init__(self, plugin: CategoryRouterPlugin):
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="set_category_model",
            description="Override the model for a specific category. Useful for testing or custom configurations.",
            parameters=[
                ToolParameter(name="category", type=ToolParameterType.STRING, description="Category name", required=True),
                ToolParameter(name="model", type=ToolParameterType.STRING, description="Model identifier (e.g., 'openai/gpt-5.4')", required=True),
                ToolParameter(name="variant", type=ToolParameterType.STRING, description="Model variant (e.g., 'high', 'xhigh')", required=False),
            ],
        )

    async def execute(self, category: str, model: str, variant: str = "default", **kwargs) -> ToolResult:
        self._plugin._categories[category] = {"model": model, "variant": variant}
        return ToolResult.ok(data={"category": category, "model": model}, summary=f"Set {category} → {model}")
```

---

### 4.3 SubAgentPlugin (Background Agent Execution)

**File**: `py_code_agent_omo/plugins/subagent.py`

**Purpose**: Parallel background agent execution with category-based model routing.

**Tools**:

| Tool | Parameters | Returns |
|---|---|---|
| `task` | `category/subagent_type, description, prompt, run_in_background, load_skills, session_id` | `{task_id, session_id, status}` |
| `background_output` | `task_id, block, timeout, full_session` | Agent output or status |
| `background_cancel` | `task_id` | Cancellation confirmation |
| `background_list` | — | List all running/completed tasks |

**Implementation**:

```python
"""Sub-Agent Plugin — parallel background agent execution.

Dependencies:
    - file:context (shared state between master and sub-agents)
    - file:heartbeat (event tracking for sub-agent lifecycle)
"""

import asyncio
import time
import uuid
from typing import Any, Dict, List, Optional

from py_code_agent.plugins.hooks import hookimpl
from py_code_agent.tools.base import BaseTool, ToolDefinition, ToolParameter, ToolParameterType, ToolResult


class SubAgentTask:
    """Tracks a single background agent task."""
    def __init__(self, task_id: str, category: str, description: str, prompt: str):
        self.id = task_id
        self.category = category
        self.description = description
        self.prompt = prompt
        self.status = "pending"  # pending | running | completed | failed
        self.result = ""
        self.error = ""
        self.session_id = ""
        self.started_at = None
        self.completed_at = None


class SubAgentPlugin:
    MAX_CONCURRENT = 4
    DEFAULT_TIMEOUT = 300

    def __init__(self):
        self._agent_ref = None
        self._tasks: Dict[str, SubAgentTask] = {}
        self._category_router = None
        self._running_count = 0

    def set_agent(self, agent):
        self._agent_ref = agent

    def _find_category_router(self):
        """Find CategoryRouterPlugin from the plugin manager."""
        if not self._agent_ref:
            return None
        pm = getattr(self._agent_ref, "plugin_manager", None)
        if not pm:
            return None
        # Try to find by name
        for name in pm.loaded_plugins:
            plugin = pm.pm.get_plugin(name)
            if plugin and hasattr(plugin, "route"):
                self._category_router = plugin
                return plugin
        return None

    @hookimpl
    def register_tools(self):
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

**Rules:**
- Fire 2-5 agents in parallel for non-trivial tasks
- Use `background_output(task_id)` to collect results
- Use `background_cancel(task_id)` to stop running tasks
- Sub-agents inherit the full plugin ecosystem from master
- Max 4 concurrent agents at a time"""

    async def spawn_task(self, task: SubAgentTask) -> None:
        """Spawn a sub-agent with category-resolved model."""
        task.status = "running"
        task.started_at = time.time()
        task.session_id = f"omo_{uuid.uuid4().hex[:8]}"
        self._running_count += 1

        try:
            # 1. Resolve category → model
            router = self._category_router or self._find_category_router()
            if router:
                routing = router.route(task.category) if hasattr(router, "route") else {"model": "openai/gpt-5.4-mini"}
            else:
                routing = {"model": "openai/gpt-5.4-mini"}

            # 2. Clone master agent with modifications
            modifications = {
                "disabled_tools": self._get_disabled_tools(task),
                "system_prompt_additions": self._build_subagent_prompt(task),
            }
            subagent = self._agent_ref.clone(modifications=modifications)

            # 3. Override LLM provider for this sub-agent's model
            model = routing.get("model", "openai/gpt-5.4-mini")
            subagent.llm = self._create_llm_provider(model, routing.get("variant"))

            # 4. Run the sub-agent
            results = []
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

    def _get_disabled_tools(self, task: SubAgentTask) -> List[str]:
        """Sub-agents shouldn't spawn more sub-agents (prevent infinite recursion)."""
        return ["task", "background_output", "background_cancel", "background_list"]

    def _build_subagent_prompt(self, task: SubAgentTask) -> str:
        return f"""## SUBTASK: {task.description}

Category: {task.category}
Task ID: {task.id}

Execute this task and return results via task_done()."""

    def _create_llm_provider(self, model: str, variant: str = None):
        """Create a LiteLLM provider for the specified model."""
        from py_code_agent.llm.litellm_provider import LiteLLMProvider
        provider = LiteLLMProvider(model=model)
        if variant:
            # Set temperature/effort based on variant
            variant_settings = {
                "default": {"temperature": 0.3},
                "high": {"temperature": 0.5},
                "xhigh": {"temperature": 0.7},
                "max": {"temperature": 0.9},
            }
            settings = variant_settings.get(variant, variant_settings["default"])
            provider.temperature = settings["temperature"]
        return provider


class TaskTool(BaseTool):
    def __init__(self, plugin: SubAgentPlugin):
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="task",
            description="Delegate work to a specialized sub-agent. Supports background execution for parallel work. "
            "Use category (visual-engineering, quick, ultrabrain, deep, artistry) for model routing, "
            "or subagent_type (oracle, librarian, explore) for specialized agents.",
            parameters=[
                ToolParameter(name="category", type=ToolParameterType.STRING, description="Task category for model routing", required=False),
                ToolParameter(name="subagent_type", type=ToolParameterType.STRING, description="Specialized agent type (oracle, librarian, explore)", required=False),
                ToolParameter(name="description", type=ToolParameterType.STRING, description="Short task description (3-5 words)", required=True),
                ToolParameter(name="prompt", type=ToolParameterType.STRING, description="Full detailed prompt for the agent", required=True),
                ToolParameter(name="run_in_background", type=ToolParameterType.BOOLEAN, description="Run asynchronously (default: true for parallel work)", required=False, default=True),
                ToolParameter(name="load_skills", type=ToolParameterType.ARRAY, description="Skill names to inject", required=False),
                ToolParameter(name="session_id", type=ToolParameterType.STRING, description="Existing session to continue", required=False),
            ],
        )

    async def execute(self, description: str, prompt: str, category: str = "", subagent_type: str = "",
                      run_in_background: bool = True, load_skills: List[str] = None, session_id: str = "", **kwargs) -> ToolResult:
        task_category = category or subagent_type or "unspecified-low"
        task_id = f"bg_{uuid.uuid4().hex[:8]}"
        task = SubAgentTask(task_id, task_category, description, prompt)
        task.session_id = session_id or task.session_id

        self._plugin._tasks[task_id] = task

        if run_in_background:
            # Launch in background
            asyncio.create_task(self._plugin.spawn_task(task))
            return ToolResult.ok(
                data={"task_id": task_id, "session_id": task.session_id, "status": "running"},
                summary=f"Launched background task: {task_id} ({description})",
            )
        else:
            # Run synchronously
            await self._plugin.spawn_task(task)
            if task.status == "completed":
                return ToolResult.ok(data={"task_id": task_id, "result": task.result}, summary=task.result[:200])
            return ToolResult.fail(f"Task failed: {task.error}")


class BackgroundOutputTool(BaseTool):
    def __init__(self, plugin: SubAgentPlugin):
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="background_output",
            description="Get output from a background task. Use full_session=true to get complete session messages.",
            parameters=[
                ToolParameter(name="task_id", type=ToolParameterType.STRING, description="Task ID to get output from", required=True),
                ToolParameter(name="block", type=ToolParameterType.BOOLEAN, description="Wait for completion", required=False, default=False),
                ToolParameter(name="timeout", type=ToolParameterType.INTEGER, description="Max wait time in seconds", required=False, default=60),
                ToolParameter(name="full_session", type=ToolParameterType.BOOLEAN, description="Return full session messages", required=False, default=False),
            ],
        )

    async def execute(self, task_id: str, block: bool = False, timeout: int = 60, full_session: bool = False, **kwargs) -> ToolResult:
        task = self._plugin._tasks.get(task_id)
        if not task:
            return ToolResult.fail(f"Task not found: {task_id}")

        if block and task.status == "running":
            # Wait for completion
            start = time.time()
            while task.status == "running" and (time.time() - start) < timeout:
                await asyncio.sleep(0.5)

        if task.status == "completed":
            return ToolResult.ok(
                data={"task_id": task_id, "status": task.status, "result": task.result, "duration": task.completed_at - task.started_at if task.completed_at and task.started_at else 0},
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
    def __init__(self, plugin: SubAgentPlugin):
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="background_cancel",
            description="Cancel a running background task.",
            parameters=[
                ToolParameter(name="task_id", type=ToolParameterType.STRING, description="Task ID to cancel", required=True),
            ],
        )

    async def execute(self, task_id: str, **kwargs) -> ToolResult:
        task = self._plugin._tasks.get(task_id)
        if not task:
            return ToolResult.fail(f"Task not found: {task_id}")
        if task.status == "running":
            task.status = "failed"
            task.error = "Cancelled by user"
            return ToolResult.ok(data={"task_id": task_id, "status": "cancelled"}, summary=f"Cancelled task {task_id}")
        return ToolResult.ok(data={"task_id": task_id, "status": task.status}, summary=f"Task {task_id} already {task.status}")


class BackgroundListTool(BaseTool):
    def __init__(self, plugin: SubAgentPlugin):
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="background_list",
            description="List all background tasks with their status.",
            parameters=[],
        )

    async def execute(self, **kwargs) -> ToolResult:
        tasks = self._plugin._tasks
        if not tasks:
            return ToolResult.ok(data={"tasks": []}, summary="No background tasks")

        lines = ["## Background Tasks\n"]
        lines.append("| Task ID | Category | Description | Status |")
        lines.append("|---------|----------|-------------|--------|")
        for tid, t in tasks.items():
            lines.append(f"| {tid[:12]} | {t.category} | {t.description[:30]} | {t.status} |")

        return ToolResult.ok(
            data={"tasks": {tid: {"category": t.category, "status": t.status, "description": t.description} for tid, t in tasks.items()}},
            summary=f"{len(tasks)} background tasks",
        )
```

---

### 4.4 DisciplinePlugin (Ralph Loop + Todo Enforcer)

**File**: `py_code_agent_omo/plugins/discipline.py`

**Purpose**: Prevent agent from quitting halfway. Enforce completion.

**Hooks**:

| Hook | Behavior |
|---|---|
| `on_agent_end()` | Check pending todos → inject continuation prompt if any remain |
| `get_system_prompt()` | Add todo discipline rules |

**Implementation**:

```python
"""Discipline Plugin — Ralph Loop + Todo Enforcer.

Prevents the agent from quitting with pending work.
"""

from py_code_agent.plugins.hooks import hookimpl
from py_code_agent.tools.base import BaseTool, ToolDefinition, ToolParameter, ToolParameterType, ToolResult


class DisciplinePlugin:
    def __init__(self):
        self._agent_ref = None
        self._force_continue = False
        self._iteration_count = 0
        self._max_iterations = 10

    def set_agent(self, agent):
        self._agent_ref = agent

    @hookimpl
    def register_tools(self):
        return [CheckTodosTool(self), EnforceContinuationTool(self)]

    @hookimpl
    def on_agent_end(self) -> None:
        """If todos remain, prevent agent from ending."""
        if self._iteration_count >= self._max_iterations:
            return  # Prevent infinite loops

        pending = self._get_pending_todos()
        if pending:
            self._force_continue = True
            self._iteration_count += 1
            # Inject continuation prompt into session
            continuation = (
                f"You have {len(pending)} pending todo items remaining.\n"
                f"You MUST continue working until all items are completed.\n"
                f"Remaining: {', '.join(t.get('content', '') for t in pending[:5])}\n"
                f"Do NOT stop. Continue with the next pending item."
            )
            if self._agent_ref and hasattr(self._agent_ref, "session"):
                self._agent_ref.session.messages.append({
                    "role": "user",
                    "content": continuation,
                })

    @hookimpl
    def get_system_prompt(self) -> str:
        return """## Todo Discipline

You are bound by your todo list. Rules:
1. Create todos BEFORE starting any non-trivial task
2. Mark items in_progress BEFORE starting each step
3. Mark items completed IMMEDIATELY after finishing
4. If you stop with pending items, the system will force you to continue
5. NEVER batch-complete multiple todos
6. If scope changes, update todos before proceeding

Your task is NOT complete until all todos are marked done."""

    def _get_pending_todos(self) -> list:
        """Extract pending todos from session messages."""
        if not self._agent_ref:
            return []
        session = getattr(self._agent_ref, "session", None)
        if not session:
            return []
        # Look for todo-related messages
        pending = []
        for msg in session.messages:
            content = msg.get("content", "")
            if "pending" in content.lower() and "todo" in content.lower():
                pending.append(msg)
        return pending


class CheckTodosTool(BaseTool):
    def __init__(self, plugin: DisciplinePlugin):
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="check_todos",
            description="Check current todo status: pending count, completed count, and remaining items.",
            parameters=[],
        )

    async def execute(self, **kwargs) -> ToolResult:
        pending = self._plugin._get_pending_todos()
        return ToolResult.ok(
            data={"pending_count": len(pending), "items": pending},
            summary=f"{len(pending)} pending todo items",
        )


class EnforceContinuationTool(BaseTool):
    def __init__(self, plugin: DisciplinePlugin):
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="enforce_continuation",
            description="Force continuation if there are pending todos. Returns continuation prompt if needed.",
            parameters=[],
        )

    async def execute(self, **kwargs) -> ToolResult:
        if self._plugin._force_continue:
            self._plugin._force_continue = False
            return ToolResult.ok(data={"should_continue": True}, summary="Continuation enforced — keep working")
        return ToolResult.ok(data={"should_continue": False}, summary="No continuation needed")
```

---

### 4.5 CommentCheckerPlugin

**File**: `py_code_agent_omo/plugins/comment_checker.py`

**Purpose**: Prevent AI-generated excessive comments.

**Hooks**:

| Hook | Behavior |
|---|---|
| `after_tool_execute(tool_name, arguments, result)` | If `write_file` used, scan for comment ratio |
| `get_system_prompt()` | Add comment guidelines |

**Implementation**:

```python
"""Comment Checker Plugin — prevents AI-generated excessive comments."""

import re
from pathlib import Path
from typing import Any, Dict, Optional

from py_code_agent.plugins.hooks import hookimpl
from py_code_agent.tools.base import BaseTool, ToolDefinition, ToolParameter, ToolParameterType, ToolResult


class CommentCheckerPlugin:
    COMMENT_PATTERNS = [
        r'^\s*#\s+(This function|This method|This class|This code)',
        r'^\s*#\s+(The following|Here we|Now we|In this)',
        r'^\s*"""\s*(This function|This method|This class)',
        r'^\s*//\s+(This function|This method|This is)',
    ]

    def __init__(self):
        self._agent_ref = None
        self._max_ratio = 0.15
        self._flagged_files = []

    def set_agent(self, agent):
        self._agent_ref = agent

    @hookimpl
    def register_tools(self):
        return [CheckCommentRatioTool(self)]

    @hookimpl
    def after_tool_execute(self, tool_name: str, arguments: Dict[str, Any], result: Any) -> None:
        if tool_name in ("write_file", "execute_bash"):
            path = arguments.get("path", "") or ""
            command = arguments.get("command", "") or ""
            # Extract file path from execute_bash commands
            if tool_name == "execute_bash" and ">" in command:
                import re
                match = re.search(r'>\s*(\S+)', command)
                if match:
                    path = match.group(1)

            if path.endswith((".py", ".js", ".ts", ".tsx", ".go", ".rs", ".css")):
                self._check_comment_ratio(path)

    def _is_comment(self, line: str) -> bool:
        line = line.strip()
        if not line:
            return False
        for pattern in self.COMMENT_PATTERNS:
            if re.match(pattern, line):
                return True
        # Generic comment detection
        if line.startswith("#") or line.startswith("//") or line.startswith("/*"):
            return True
        return False

    def _check_comment_ratio(self, path: str) -> None:
        try:
            content = Path(path).read_text()
        except Exception:
            return

        lines = content.splitlines()
        if len(lines) < 10:
            return  # Skip small files

        comment_lines = sum(1 for l in lines if self._is_comment(l))
        ratio = comment_lines / len(lines)

        if ratio > self._max_ratio:
            self._flagged_files.append({"path": path, "ratio": ratio, "lines": len(lines)})
            # Store in context for LLM to see
            if self._agent_ref:
                pm = getattr(self._agent_ref, "plugin_manager", None)
                if pm:
                    ctx = pm.pm.get_plugin("file:context")
                    if ctx:
                        ctx.write(f"comment_flag_{path}", f"Excessive comments in {path}: {ratio:.0%} ratio")

    @hookimpl
    def get_system_prompt(self) -> str:
        return """## Comment Guidelines

Write code like a senior engineer:
- Comments explain WHY, not WHAT (code should be self-documenting)
- No "This function does X" comments
- No excessive docstrings for simple methods
- Comment ratio should stay below 15%
- If you need to explain complex logic, use meaningful variable/function names instead"""


class CheckCommentRatioTool(BaseTool):
    def __init__(self, plugin: CommentCheckerPlugin):
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="check_comment_ratio",
            description="Check comment ratio for a file. Returns ratio and whether it exceeds the threshold.",
            parameters=[
                ToolParameter(name="path", type=ToolParameterType.STRING, description="File path to check", required=True),
            ],
        )

    async def execute(self, path: str, **kwargs) -> ToolResult:
        try:
            content = Path(path).read_text()
        except Exception as e:
            return ToolResult.fail(f"Cannot read file: {e}")

        lines = content.splitlines()
        comment_lines = sum(1 for l in lines if self._plugin._is_comment(l))
        ratio = comment_lines / max(len(lines), 1)

        return ToolResult.ok(
            data={"path": path, "ratio": ratio, "comment_lines": comment_lines, "total_lines": len(lines), "exceeds_threshold": ratio > self._plugin._max_ratio},
            summary=f"Comment ratio: {ratio:.0%} ({'exceeds' if ratio > self._plugin._max_ratio else 'within'} {self._plugin._max_ratio:.0%} threshold)",
        )
```

---

### 4.6 ThinkModePlugin

**File**: `py_code_agent_omo/plugins/think_mode.py`

**Purpose**: Structured thinking mode for complex reasoning before action.

**Tools**:

| Tool | Parameters | Returns |
|---|---|---|
| `ultrathink` | `problem: str` | Structured analysis with options, tradeoffs, recommendation |

**Implementation**:

```python
"""Think Mode Plugin — structured thinking for complex reasoning."""

from py_code_agent.plugins.hooks import hookimpl
from py_code_agent.tools.base import BaseTool, ToolDefinition, ToolParameter, ToolParameterType, ToolResult

THINK_PROMPT = """Analyze this problem systematically:

Problem: {problem}

Provide a structured analysis:
1. **Understanding**: What is the core problem?
2. **Constraints**: What limitations exist?
3. **Options**: List 3 possible approaches
4. **Tradeoffs**: For each option, list pros/cons
5. **Recommendation**: Which option is best and why?

Return JSON:
{{
  "understanding": "...",
  "constraints": ["...", "..."],
  "options": [
    {{"name": "...", "pros": ["..."], "cons": ["..."]}},
  ],
  "recommendation": {{"option": "...", "reason": "..."}}
}}"""


class ThinkModePlugin:
    def __init__(self):
        self._agent_ref = None

    def set_agent(self, agent):
        self._agent_ref = agent

    @hookimpl
    def register_tools(self):
        return [UltrathinkTool(self)]

    @hookimpl
    def get_system_prompt(self) -> str:
        return """## Think Mode

For complex problems, use `ultrathink` before acting:
- Architecture decisions
- Multi-system changes
- Security-sensitive modifications
- Performance-critical optimizations

Think mode forces structured reasoning before implementation."""


class UltrathinkTool(BaseTool):
    def __init__(self, plugin: ThinkModePlugin):
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="ultrathink",
            description="Structured thinking tool for complex problems. Forces analysis of options, tradeoffs, and recommendations before acting.",
            parameters=[
                ToolParameter(name="problem", type=ToolParameterType.STRING, description="The problem to analyze", required=True),
            ],
        )

    async def execute(self, problem: str, **kwargs) -> ToolResult:
        if not self._plugin._agent_ref:
            return ToolResult.fail("Agent not available")

        try:
            from py_code_agent.llm.litellm_provider import Message, MessageRole
            messages = [Message(role=MessageRole.USER, content=THINK_PROMPT.format(problem=problem))]
            response = await self._plugin._agent_ref.llm.complete(messages, temperature=0.3)
            content = response.get("content", "")
            # Parse JSON response
            import json, re
            text = content.strip()
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)
            data = json.loads(text)
            return ToolResult.ok(data=data, summary=data.get("recommendation", {}).get("reason", "Analysis complete"))
        except Exception as e:
            return ToolResult.fail(f"Think mode failed: {e}")
```

---

## 5. Config Schema

**File**: `~/.config/py-code-agent/omo.yaml`

```yaml
# Oh My OpenCode Configuration for Py Code Agent
# Third-party plugin collection: py-code-agent-omo

# ── Intent Gate ──
intent_gate:
  enabled: true
  model: "openai/gpt-5.4-mini"  # cheap model for classification
  threshold: 0.7

# ── Category Router ──
category_router:
  enabled: true
  categories:
    visual-engineering:
      model: "google/gemini-3.1-pro"
      variant: "high"
    ultrabrain:
      model: "openai/gpt-5.4"
      variant: "xhigh"
    deep:
      model: "anthropic/claude-opus-4-6"
    quick:
      model: "openai/gpt-5.4-mini"
    artistry:
      model: "anthropic/claude-sonnet-4.6"
    unspecified-high:
      model: "anthropic/claude-opus-4.6"
    unspecified-low:
      model: "openai/gpt-5.4-mini"
    writing:
      model: "anthropic/claude-sonnet-4.6"
  agents:
    oracle:
      model: "openai/gpt-5.4"
      variant: "high"
    librarian:
      model: "anthropic/claude-sonnet-4.6"
    explore:
      model: "xai/grok-code-fast-1"
    frontend-engineer:
      model: "google/gemini-3.1-pro"
  provider_fallbacks:
    anthropic: ["openai", "google"]
    openai: ["anthropic", "google"]

# ── Sub-Agent Execution ──
subagent:
  enabled: true
  max_concurrent: 4
  default_timeout: 300

# ── Discipline ──
discipline:
  enabled: true
  ralph_loop:
    enabled: true
    max_iterations: 10
  comment_checker:
    enabled: true
    max_comment_ratio: 0.15
```

---

## 6. Integration Mechanism

### 6.1 How OMO Plugins Connect to Py Code Agent

| OMO Need | Py Code Agent API Used | How |
|---|---|---|
| Plugin discovery | `entry_points(group="py_code_agent.plugins")` | pyproject.toml entry points |
| Hook registration | `@hookimpl` decorator | pluggy's hookimpl |
| Tool registration | `register_tools()` hook | Returns `List[BaseTool]` |
| Agent access | `set_agent(agent)` | PluginManager calls this automatically |
| LLM calls | `agent.llm.complete(messages)` | Via LiteLLMProvider |
| Sub-agent spawning | `agent.clone(modifications={...})` | PlanPlugin already does this |
| Shared state | `ContextPlugin` via `plugin_manager.pm.get_plugin("file:context")` | Cross-plugin communication |
| Event tracking | `HeartbeatPlugin` via `plugin_manager.pm.get_plugin("file:heartbeat")` | Lifecycle monitoring |
| Config loading | `~/.config/py-code-agent/omo.yaml` | Independent YAML loading |
| Error enhancement | `enhance_tool_error()` hook | Priority-based error diagnosis |

### 6.2 What OMO Does NOT Touch

| Component | Why |
|---|---|
| `Agent.run()` | OMO doesn't modify the agent loop |
| `Session` | OMO reads session messages but doesn't modify internals |
| `LiteLLMProvider` internals | OMO creates new instances for sub-agents, doesn't modify the host's |
| `PluginManager` internals | OMO uses public APIs only |
| Core config | OMO uses its own `omo.yaml`, doesn't touch Py Code Agent's config |

### 6.3 Plugin Dependency Chain

```
IntentGatePlugin
    │
    ├── writes intent to ContextPlugin
    │
CategoryRouterPlugin
    │
    ├── reads intent from ContextPlugin (optional)
    ├── provides route() method to SubAgentPlugin
    │
SubAgentPlugin
    │
    ├── uses agent.clone() from host
    ├── uses CategoryRouterPlugin.route()
    ├── uses ContextPlugin for shared state
    │
DisciplinePlugin
    │
    ├── reads todos from session messages
    ├── injects continuation prompts into session
    │
CommentCheckerPlugin
    │
    ├── scans files after write_file/execute_bash
    ├── flags excessive comments via ContextPlugin
    │
ThinkModePlugin
    │
    └── uses agent.llm for structured analysis
```

---

## 7. Installation & Usage

### 7.1 Installation

```bash
pip install py-code-agent-omo
```

That's it. Py Code Agent's entry-point discovery auto-loads all 6 plugins.

### 7.2 Configuration

```bash
# Create config file
mkdir -p ~/.config/py-code-agent
cp omo.yaml.example ~/.config/py-code-agent/omo.yaml
# Edit with your models/providers
```

### 7.3 Selective Enable/Disable

In Py Code Agent's config (`~/.config/py-code-agent/config.yaml`):

```yaml
plugins:
  enabled:
    - file:intent-gate
    - file:category-router
    - file:subagent
    - file:discipline
    - file:comment-checker
    - file:think-mode
  disabled: []  # Disable specific plugins here
```

### 7.4 Verification

```
User: "load_plugins(plugins='omo', reason='enable OMO features')"
→ All 6 plugins loaded
→ Tools available: classify_intent, route_task, task, background_output, background_cancel, background_list, check_todos, enforce_continuation, check_comment_ratio, ultrathink
```

---

## 8. Implementation Phases

### Phase 1: Package Foundation (Week 1)

| Item | File | Effort |
|---|---|---|
| Package skeleton + pyproject.toml | `pyproject.toml`, `__init__.py` | 1h |
| Config loader | `py_code_agent_omo/config.py` | 2h |
| CategoryRouterPlugin | `plugins/category_router.py` | 3h |

### Phase 2: Core Plugins (Week 1-2)

| Item | File | Effort |
|---|---|---|
| IntentGatePlugin | `plugins/intent_gate.py` | 3h |
| SubAgentPlugin | `plugins/subagent.py` | 6h |
| Agent prompts | `agents/*.py` | 4h |

### Phase 3: Discipline & Polish (Week 2)

| Item | File | Effort |
|---|---|---|
| DisciplinePlugin | `plugins/discipline.py` | 3h |
| CommentCheckerPlugin | `plugins/comment_checker.py` | 2h |
| ThinkModePlugin | `plugins/think_mode.py` | 2h |
| Integration tests | `tests/test_*.py` | 6h |

### Phase 4: Distribution (Week 2-3)

| Item | Effort |
|---|---|
| PyPI packaging | 2h |
| Documentation | 4h |
| Example configs | 1h |

---

## 9. Risk Analysis

| Risk | Impact | Mitigation |
|---|---|---|
| `Agent.clone()` API changes in host | High | Pin `py-code-agent>=0.1.0,<0.2.0`; test against each release |
| `agent.llm` provider interface changes | High | Wrap in adapter; fallback to direct LiteLLM |
| Concurrent sub-agents exhaust API rate limits | Medium | Configurable `max_concurrent`; per-provider rate limiting |
| Cross-plugin communication breaks if built-in plugins disabled | Medium | Graceful degradation; each plugin works standalone |
| Config complexity for users | Medium | Sensible defaults; only power users customize |

---

## 10. Success Metrics

| Metric | Target |
|---|---|
| Task completion rate | > 90% (vs ~60% single-agent baseline) |
| Average task time | < 50% of single-agent time (parallel execution) |
| API cost per task | < 80% of single-agent cost (cheaper models for simple tasks) |
| Agent quit rate (mid-task) | < 5% (DisciplinePlugin enforcement) |
| Comment ratio in generated code | < 15% (CommentCheckerPlugin) |
| Package install success rate | > 99% (pip install, entry-point discovery) |

---

## Appendix A: Tool Call Flow

```
User: "ultrawork: rebuild the auth system"
  │
  ▼
IntentGatePlugin.on_agent_start()
  → classifies: intent="implementation", confidence=0.95
  → stores in ContextPlugin for other plugins
  │
  ▼
Sisyphus (main agent) plans the task
  │
  ▼
Sisyphus calls: task(category="deep", description="Analyze auth...", prompt="...", run_in_background=True)
  │
  ▼
SubAgentPlugin.task()
  1. CategoryRouterPlugin.route("deep") → {model: "claude-opus-4-6"}
  2. agent.clone(disabled_tools=[...], system_prompt_additions="...")
  3. Create new LiteLLMProvider for claude-opus-4-6
  4. Launch subagent.run() in asyncio.create_task()
  5. Return {task_id: "bg_abc123", status: "running"}
  │
  ▼
Sisyphus fires 3 more tasks in parallel:
  - task(category="visual-engineering", ...) → Gemini
  - task(subagent_type="explore", ...) → Grok Code
  - task(subagent_type="librarian", ...) → Sonnet
  │
  ▼
Sisyphus calls: background_output(task_id="bg_abc123")
  → Collects results
  → Synthesizes
  → Continues to next phase
  │
  ▼
DisciplinePlugin.on_agent_end()
  → Checks pending todos
  → If any remain, injects continuation prompt
  → Agent continues until all done
```

---

## Appendix B: Package File Structure

```
py-code-agent-omo/
├── pyproject.toml                 # Entry points, dependencies
├── README.md                      # Installation + usage guide
├── omo.yaml.example               # Example configuration
│
├── py_code_agent_omo/
│   ├── __init__.py                # Package init, version
│   ├── config.py                  # OMO config loader (YAML → Pydantic)
│   │
│   ├── plugins/
│   │   ├── __init__.py
│   │   ├── intent_gate.py         # IntentGatePlugin
│   │   ├── category_router.py     # CategoryRouterPlugin
│   │   ├── subagent.py            # SubAgentPlugin
│   │   ├── discipline.py          # DisciplinePlugin
│   │   ├── comment_checker.py     # CommentCheckerPlugin
│   │   └── think_mode.py          # ThinkModePlugin
│   │
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── oracle.py              # Oracle agent prompt
│   │   ├── librarian.py           # Librarian agent prompt
│   │   ├── explore.py             # Explore agent prompt
│   │   └── frontend_engineer.py   # Frontend engineer prompt
│   │
│   └── tools/
│       └── __init__.py            # Shared tool utilities
│
└── tests/
    ├── test_intent_gate.py
    ├── test_category_router.py
    ├── test_subagent.py
    ├── test_discipline.py
    ├── test_comment_checker.py
    └── test_think_mode.py
```

---

## Appendix C: Entry Point Registration Detail

Py Code Agent discovers OMO plugins via Python's entry point mechanism:

```python
# pyproject.toml
[project.entry-points."py_code_agent.plugins"]
intent-gate = "py_code_agent_omo.plugins.intent_gate"
category-router = "py_code_agent_omo.plugins.category_router"
subagent = "py_code_agent_omo.plugins.subagent"
discipline = "py_code_agent_omo.plugins.discipline"
comment-checker = "py_code_agent_omo.plugins.comment_checker"
think-mode = "py_code_agent_omo.plugins.think_mode"
```

Each entry point module must export a class with `register_tools` method:

```python
# py_code_agent_omo/plugins/intent_gate.py
class IntentGatePlugin:
    def register_tools(self):
        return [ClassifyIntentTool(self)]
```

Py Code Agent's `PluginManager._load_entry_point()` will:
1. Load the module via `ep.load()`
2. Instantiate the class: `plugin_instance = plugin()`
3. Register with pluggy: `self.pm.register(plugin_instance, name=name)`
4. Call `set_agent(agent)` if the plugin has that method

**Zero modifications to Py Code Agent required.**
