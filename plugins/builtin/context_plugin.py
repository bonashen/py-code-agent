"""Context Plugin — provides context sharing between master and subagents.

This plugin enables agents to share state and findings during complex task execution.
It is designed to be used by PlanPlugin for subtask coordination, but can also be
used directly by any agent that needs to share context.

Key Features:
- Key-value store for context data
- Thread-safe operations
- JSON serialization support
- Aggregation for multi-source context
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from py_code_agent.plugins.hooks import hookimpl
from py_code_agent.tools.base import (
    BaseTool,
    ToolDefinition,
    ToolParameter,
    ToolParameterType,
    ToolResult,
)


@dataclass
class ContextEntry:
    """Single context entry."""
    key: str
    value: str
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    source: str = "agent"  # "agent", "subtask", "plugin"


class ContextPlugin:
    """Plugin for context sharing between tasks/subagents.

    Provides a thread-safe key-value store for sharing state,
    findings, and results between different execution contexts.

    Usage:
        - PlanPlugin uses this for subtask coordination
        - Master agent stores findings for subagents to read
        - Subagents can write results back to shared context
    """

    def __init__(self):
        self._store: Dict[str, ContextEntry] = {}
        self._lock = threading.RLock()
        self._history: List[Dict[str, Any]] = []
        self._max_history = 100

    def set_agent(self, agent: Any) -> None:
        """Receive agent reference for advanced features."""
        pass

    @hookimpl
    def register_tools(self) -> List[BaseTool]:
        return [
            ContextTool(self),
            ContextListTool(self),
            ContextAggregateTool(self),
            ContextClearTool(self),
        ]

    @hookimpl
    def on_agent_start(self, input: str) -> None:
        """Clear stale context on new agent session."""
        # Keep history but mark new session
        pass

    @hookimpl
    def get_system_prompt(self) -> str:
        """Provide context tool guidelines."""
        return """## Context Sharing

When working on multi-step tasks, use context tools to share findings:

- `context(action="write", key="...", value="...")` — Store findings
- `context(action="read", key="...")` — Read stored context
- `context(action="list")` — List all context keys
- `context(action="aggregate")` — Get all context combined

This enables coordination between subtasks and preserves important discoveries."""

    # ── Internal API ────────────────────────────────────────────────────

    def write(self, key: str, value: str, source: str = "agent") -> bool:
        """Write a context entry (thread-safe)."""
        with self._lock:
            existing = self._store.get(key)
            entry = ContextEntry(
                key=key,
                value=value,
                source=source,
                updated_at=datetime.now(),
            )
            if existing:
                entry.created_at = existing.created_at

            self._store[key] = entry
            self._add_history("write", key, source)
            return True

    def read(self, key: str) -> Optional[str]:
        """Read a context entry (thread-safe)."""
        with self._lock:
            entry = self._store.get(key)
            return entry.value if entry else None

    def list_keys(self) -> List[str]:
        """List all context keys (thread-safe)."""
        with self._lock:
            return list(self._store.keys())

    def get_all(self) -> Dict[str, str]:
        """Get all context as dict (thread-safe)."""
        with self._lock:
            return {k: v.value for k, v in self._store.items()}

    def clear(self, key: Optional[str] = None) -> int:
        """Clear context (thread-safe)."""
        with self._lock:
            if key:
                removed = 1 if key in self._store else 0
                self._store.pop(key, None)
                self._add_history("clear", key, "agent")
                return removed
            else:
                count = len(self._store)
                self._store.clear()
                self._add_history("clear_all", "*", "agent")
                return count

    def _add_history(self, action: str, key: str, source: str) -> None:
        """Add entry to history."""
        self._history.append({
            "action": action,
            "key": key,
            "source": source,
            "timestamp": datetime.now().isoformat(),
        })
        # Trim history
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]


class ContextTool(BaseTool):
    """Share context between tasks — store or read findings."""

    def __init__(self, plugin: ContextPlugin):
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="context",
            description="Share context between tasks. Store findings, read shared data, "
                        "or aggregate all context. Use to build collective understanding "
                        "across subtasks.",
            parameters=[
                ToolParameter(
                    name="action",
                    type=ToolParameterType.STRING,
                    description="Action: 'write', 'read', 'list', or 'aggregate'",
                    required=True,
                ),
                ToolParameter(
                    name="key",
                    type=ToolParameterType.STRING,
                    description="Key name for context (e.g., 'directory_structure', 'analysis_result'). "
                                "Required for write/read actions.",
                    required=False,
                ),
                ToolParameter(
                    name="value",
                    type=ToolParameterType.STRING,
                    description="Value to store (for write action). Use simple text, "
                                "avoid special characters and newlines in JSON.",
                    required=False,
                ),
            ],
        )

    async def execute(
        self,
        action: str,
        key: str = "",
        value: str = "",
        **kwargs: Any
    ) -> ToolResult:
        action = action.lower().strip()

        if action == "write":
            if not key:
                return ToolResult.fail("Key is required for write action")
            if not value:
                return ToolResult.fail("Value is required for write action")

            # Validate value is simple text (not tool calls)
            if any(x in value.lower() for x in ["context(", "task_done(", "skill_"]):
                return ToolResult.fail(
                    "Value contains tool call syntax. Store plain text results only."
                )

            self._plugin.write(key, value)
            return ToolResult.ok(
                data={"key": key, "stored": True},
                summary=f"Stored context: {key} ({len(value)} chars)"
            )

        elif action == "read":
            if not key:
                return ToolResult.fail("Key is required for read action")
            val = self._plugin.read(key)
            if val is None:
                return ToolResult.fail(f"Key not found: {key}")
            return ToolResult.ok(
                data={"key": key, "value": val},
                summary=f"Read context: {key}"
            )

        elif action == "list":
            keys = self._plugin.list_keys()
            return ToolResult.ok(
                data={"keys": keys, "count": len(keys)},
                summary=f"Available context keys: {', '.join(keys) if keys else '(none)'}"
            )

        elif action == "aggregate":
            all_ctx = self._plugin.get_all()
            if not all_ctx:
                return ToolResult.ok(
                    data={"context": {}, "count": 0},
                    summary="No context available"
                )

            # Format as readable text
            formatted = []
            for k, v in all_ctx.items():
                formatted.append(f"## {k}\n{v}")

            return ToolResult.ok(
                data={
                    "context": all_ctx,
                    "formatted": "\n\n".join(formatted),
                    "count": len(all_ctx),
                },
                summary=f"Aggregated {len(all_ctx)} context items"
            )

        return ToolResult.fail(
            f"Unknown action: {action}. Use: write, read, list, or aggregate"
        )


class ContextListTool(BaseTool):
    """List all context keys — convenience wrapper."""

    def __init__(self, plugin: ContextPlugin):
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="context_list",
            description="List all available context keys. Convenience wrapper for "
                        "context(action='list').",
            parameters=[],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        keys = self._plugin.list_keys()
        return ToolResult.ok(
            data={"keys": keys, "count": len(keys)},
            summary=f"{len(keys)} context keys available"
        )


class ContextAggregateTool(BaseTool):
    """Aggregate all context — convenience wrapper."""

    def __init__(self, plugin: ContextPlugin):
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="context_aggregate",
            description="Aggregate all context into a combined summary. "
                        "Convenience wrapper for context(action='aggregate').",
            parameters=[],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        all_ctx = self._plugin.get_all()
        if not all_ctx:
            return ToolResult.ok(
                data={"context": {}, "count": 0},
                summary="No context to aggregate"
            )

        formatted = []
        for k, v in all_ctx.items():
            formatted.append(f"## {k}\n{v}")

        return ToolResult.ok(
            data={
                "context": all_ctx,
                "formatted": "\n\n".join(formatted),
                "count": len(all_ctx),
            },
            summary=f"Aggregated {len(all_ctx)} context items"
        )


class ContextClearTool(BaseTool):
    """Clear context — for cleanup."""

    def __init__(self, plugin: ContextPlugin):
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="context_clear",
            description="Clear context data. Use to reset context state "
                        "between major task phases.",
            parameters=[
                ToolParameter(
                    name="key",
                    type=ToolParameterType.STRING,
                    description="Specific key to clear. If omitted, clears all context.",
                    required=False,
                ),
            ],
        )

    async def execute(self, key: str = "", **kwargs: Any) -> ToolResult:
        count = self._plugin.clear(key if key else None)
        if key:
            return ToolResult.ok(
                data={"cleared_key": key, "count": 1},
                summary=f"Cleared context key: {key}"
            )
        return ToolResult.ok(
            data={"cleared_count": count},
            summary=f"Cleared {count} context entries"
        )
