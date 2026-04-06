"""Discipline Plugin — Ralph Loop + Todo Enforcer."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from py_code_agent.plugins.hooks import hookimpl
from py_code_agent.tools.base import (
    BaseTool,
    ToolDefinition,
    ToolParameter,
    ToolParameterType,
    ToolResult,
)

from py_code_agent_omo.config import get_omo_config


class DisciplinePlugin:
    """Prevents the agent from quitting with pending work.

    Combines Ralph Loop (auto-continuation) and Todo Enforcer
    (pending todo detection) to ensure task completion.
    """

    def __init__(self) -> None:
        self._agent_ref: Any = None
        self._force_continue = False
        self._iteration_count = 0
        self._config = get_omo_config()

    def set_agent(self, agent: Any) -> None:
        self._agent_ref = agent

    @hookimpl
    def register_tools(self) -> List[BaseTool]:
        return [CheckTodosTool(self), EnforceContinuationTool(self)]

    @hookimpl
    def on_agent_end(self) -> None:
        discipline_cfg = self._config.discipline
        ralph_cfg = discipline_cfg.get("ralph_loop", {})
        if not ralph_cfg.get("enabled", True):
            return

        max_iter = ralph_cfg.get("max_iterations", 10)
        if self._iteration_count >= max_iter:
            return

        pending = self._get_pending_todos()
        if pending:
            self._force_continue = True
            self._iteration_count += 1
            continuation = (
                f"You have {len(pending)} pending todo items remaining.\n"
                f"You MUST continue working until all items are completed.\n"
                f"Remaining: {', '.join(str(t) for t in pending[:5])}\n"
                f"Do NOT stop. Continue with the next pending item."
            )
            if self._agent_ref:
                session = getattr(self._agent_ref, "session", None)
                if session:
                    messages = getattr(session, "messages", None)
                    if messages is not None:
                        messages.append({"role": "user", "content": continuation})

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

    def _get_pending_todos(self) -> List[str]:
        if not self._agent_ref:
            return []
        session = getattr(self._agent_ref, "session", None)
        if not session:
            return []
        messages = getattr(session, "messages", [])
        pending = []
        for msg in messages:
            content = msg.get("content", "") if isinstance(msg, dict) else ""
            todos = re.findall(r"- \[ \] (.+)", content)
            pending.extend(todos)
        return pending


class CheckTodosTool(BaseTool):
    def __init__(self, plugin: DisciplinePlugin) -> None:
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="check_todos",
            description="Check current todo status: pending count and remaining items.",
            parameters=[],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        pending = self._plugin._get_pending_todos()
        return ToolResult.ok(
            data={"pending_count": len(pending), "items": pending},
            summary=f"{len(pending)} pending todo items",
        )


class EnforceContinuationTool(BaseTool):
    def __init__(self, plugin: DisciplinePlugin) -> None:
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="enforce_continuation",
            description="Force continuation if there are pending todos.",
            parameters=[],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        if self._plugin._force_continue:
            self._plugin._force_continue = False
            return ToolResult.ok(
                data={"should_continue": True},
                summary="Continuation enforced — keep working",
            )
        return ToolResult.ok(
            data={"should_continue": False},
            summary="No continuation needed",
        )
