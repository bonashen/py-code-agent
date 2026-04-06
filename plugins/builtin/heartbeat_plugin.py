"""Heartbeat plugin — aggregates agent activity into heartbeat messages for external monitoring.

Hooks into all agent lifecycle events and tool calls, builds heartbeat
payloads, and exposes them via:
- `get_heartbeat_status` tool (pull model)
- Optional HTTP push to configured endpoint (push model)

Heartbeat messages are stored in a rolling buffer (configurable size, default 1000).
"""

from __future__ import annotations

import asyncio
import json
import logging
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

logger = logging.getLogger(__name__)

__version__ = "0.1.0"


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class HeartbeatMessage:
    """A single heartbeat event emitted by the agent."""

    id: str
    timestamp: float  # time.time()
    event_type: str = "plugin_heartbeat"  # "agent_start" | "agent_end" | "llm_call" | "llm_response" | "tool_before" | "tool_after" | "plugin_heartbeat"
    session_id: str = ""
    sequence: int = 0  # auto-increment per session
    # Unified plugin heartbeat fields
    event: str = ""  # Specific event type (e.g., "scored", "started")
    plugin_name: str = ""  # Plugin that emitted the event
    plugin_id: str = ""  # Plugin instance ID
    data: Dict[str, Any] = field(default_factory=dict)  # Event-specific data
    # LLM events
    llm_model: str = ""
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    llm_tool_calls: int = 0
    # Tool events
    tool_name: str = ""
    tool_duration_ms: float = 0.0
    tool_success: bool = True
    tool_error: str = ""
    # General
    message_count: int = 0
    active_tools: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert heartbeat message to dictionary."""
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "session_id": self.session_id,
            "sequence": self.sequence,
            "event": self.event,
            "plugin_name": self.plugin_name,
            "plugin_id": self.plugin_id,
            "data": self.data,
            "llm_model": self.llm_model,
            "llm_input_tokens": self.llm_input_tokens,
            "llm_output_tokens": self.llm_output_tokens,
            "llm_tool_calls": self.llm_tool_calls,
            "tool_name": self.tool_name,
            "tool_duration_ms": self.tool_duration_ms,
            "tool_success": self.tool_success,
            "tool_error": self.tool_error,
            "message_count": self.message_count,
            "active_tools": self.active_tools,
            "extra": self.extra,
        }


# ─────────────────────────────────────────────────────────────────────────────
# HeartbeatPlugin
# ─────────────────────────────────────────────────────────────────────────────


class HeartbeatPlugin:
    """Aggregates agent activity into heartbeat messages for external monitoring.

    Hooks into all agent lifecycle events and tool calls, builds heartbeat
    payloads, and exposes them via:
    - `get_heartbeat_status` tool (pull model)
    - Optional HTTP push to configured endpoint (push model)

    Heartbeat messages are stored in a rolling buffer (configurable size, default 1000).
    """

    def __init__(self):
        self._agent_ref: Optional[Any] = None
        self._messages: List[HeartbeatMessage] = []
        self._max_buffer: int = 1000
        self._session_id: str = ""
        self._sequence: int = 0
        self._active: bool = False
        self._tool_timers: Dict[str, float] = {}  # tool_name -> start time
        self._last_llm_tokens: Dict[str, int] = {}  # response stats
        self._push_endpoint: str = ""
        self._push_interval: int = 30  # seconds
        self._last_push: float = 0
        self._enabled: bool = True
        self._session_start: float = 0

    # ── Internal helpers ───────────────────────────────────────────────────

    def _append(self, event_type: str, **kwargs) -> None:
        """Append a heartbeat message to the buffer."""
        if not self._enabled:
            return
        self._sequence += 1
        msg = HeartbeatMessage(
            id=str(uuid.uuid4()),
            timestamp=time.time(),
            event_type=event_type,
            session_id=self._session_id,
            sequence=self._sequence,
            **{k: v for k, v in kwargs.items() if k in HeartbeatMessage.__dataclass_fields__},
        )
        # Set extra for fields not in dataclass
        for k, v in kwargs.items():
            if k not in HeartbeatMessage.__dataclass_fields__:
                msg.extra[k] = v
        self._messages.append(msg)
        # Rolling buffer
        if len(self._messages) > self._max_buffer:
            self._messages = self._messages[-self._max_buffer:]

    # ── Hooks ───────────────────────────────────────────────────────────────

    @hookimpl
    def register_tools(self) -> List[BaseTool]:
        return [self.GetHeartbeatStatusTool(plugin=self)]

    @hookimpl
    def set_agent(self, agent: Any) -> None:
        self._agent_ref = agent
        # Read push config from agent.config if available
        try:
            hb = getattr(agent, "config", None)
            if hb and hasattr(hb, "heartbeat"):
                self._enabled = getattr(hb.heartbeat, "enabled", True)
                self._push_interval = getattr(hb.heartbeat, "interval", 30)
        except Exception:
            pass

    @hookimpl
    def on_agent_start(self, input: str) -> None:
        self._session_id = str(uuid.uuid4())
        self._sequence = 0
        self._active = True
        self._session_start = time.time()
        self._messages.clear()
        self._append("agent_start", extra={"input_preview": input[:200]})

    @hookimpl
    def on_agent_end(self) -> None:
        self._active = False
        self._append("agent_end", extra={"session_duration_s": time.time() - self._session_start})

    @hookimpl
    def on_llm_call(self, messages: List[Dict], tools: List[Dict]) -> None:
        self._append(
            "llm_call",
            message_count=len(messages),
            active_tools=[t.get("function", {}).get("name", "") for t in tools],
            extra={"tool_count": len(tools), "message_count": len(messages)},
        )

    @hookimpl
    def on_llm_response(self, response: Any) -> None:
        # Extract usage stats from response
        usage = {}
        if hasattr(response, "get"):
            usage = response.get("usage") or {}
        elif hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": getattr(response.usage, "prompt_tokens", 0),
                "completion_tokens": getattr(response.usage, "completion_tokens", 0),
                "total_tokens": getattr(response.usage, "total_tokens", 0),
            }

        # Count tool calls
        tool_calls = []
        if hasattr(response, "get"):
            tool_calls = response.get("tool_calls") or []
        elif hasattr(response, "tool_calls"):
            tool_calls = response.tool_calls or []

        self._append(
            "llm_response",
            llm_input_tokens=usage.get("prompt_tokens", 0),
            llm_output_tokens=usage.get("completion_tokens", 0),
            llm_tool_calls=len(tool_calls),
        )

    @hookimpl
    def before_tool_execute(self, tool_name: str, arguments: Dict[str, Any]) -> None:
        self._tool_timers[tool_name] = time.time()
        self._append("tool_before", tool_name=tool_name, extra={"args_preview": str(arguments)[:200]})

    @hookimpl
    def after_tool_execute(self, tool_name: str, arguments: Dict[str, Any], result: Any) -> None:
        duration = time.time() - self._tool_timers.pop(tool_name, time.time())
        error = ""
        success = True
        if hasattr(result, "is_success"):
            success_call = getattr(result, "is_success", None)
            if callable(success_call):
                success = success_call()
            else:
                success = bool(success_call)
            if not success:
                error = str(getattr(result, "error", ""))[:200]
        elif hasattr(result, "get") and result.get("error"):
            success = False
            error = str(result.get("error", ""))[:200]
        self._append(
            "tool_after",
            tool_name=tool_name,
            tool_duration_ms=duration * 1000,
            tool_success=success,
            tool_error=error,
        )

    @hookimpl
    def on_plugin_heartbeat(
        self,
        event: str,
        data: Dict[str, Any],
    ) -> None:
        """Receive unified plugin heartbeat events."""
        if not self._enabled:
            return

        plugin_name = data.get("plugin_name", "")
        plugin_id = data.get("plugin_id", "")

        clean_data = {k: v for k, v in data.items()
                      if k not in ("plugin_name", "plugin_id")}

        self._append(
            "plugin_heartbeat",
            event=event,
            plugin_name=plugin_name,
            plugin_id=plugin_id,
            data=clean_data,
        )

    # ── Tools ─────────────────────────────────────────────────────────────

    class GetHeartbeatStatusTool(BaseTool):
        """Get the current agent heartbeat status."""

        def __init__(self, plugin: "HeartbeatPlugin"):
            self._plugin = plugin

        @property
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="get_heartbeat_status",
                description="Get the current agent heartbeat status: active sessions, recent events, LLM/token stats, and tool call history. Use this to monitor agent health and activity.",
                parameters=[
                    ToolParameter(
                        name="limit",
                        type=ToolParameterType.INTEGER,
                        description="Maximum number of recent heartbeat messages to return (default 50, max 500)",
                        required=False,
                    ),
                    ToolParameter(
                        name="event_type",
                        type=ToolParameterType.STRING,
                        description="Filter by event type: agent_start, agent_end, llm_call, llm_response, tool_before, tool_after",
                        required=False,
                    ),
                ],
            )

        async def execute(self, limit: int = 50, event_type: str = "", **kwargs) -> ToolResult:
            limit = min(max(limit, 1), 500)
            msgs = self._plugin._messages[-limit:]
            if event_type:
                msgs = [m for m in msgs if m.event_type == event_type]

            total_llm_in = sum(m.llm_input_tokens for m in msgs)
            total_llm_out = sum(m.llm_output_tokens for m in msgs)
            total_tool_calls = sum(1 for m in msgs if m.event_type in ("tool_before", "tool_after"))
            tool_success = sum(1 for m in msgs if m.event_type == "tool_after" and m.tool_success)
            tool_fail = sum(1 for m in msgs if m.event_type == "tool_after" and not m.tool_success)
            active = self._plugin._active
            session_dur = time.time() - self._plugin._session_start if self._plugin._session_start else 0

            summary = (
                f"Active={active}, {len(msgs)} msgs, "
                f"LLM tokens: {total_llm_in}+{total_llm_out}={total_llm_in+total_llm_out}, "
                f"Tool calls: {total_tool_calls} ({tool_success}✅ {tool_fail}❌), "
                f"session={session_dur:.0f}s"
            )

            return ToolResult.ok(
                data={
                    "active": active,
                    "session_id": self._plugin._session_id,
                    "session_duration_s": round(session_dur, 1),
                    "total_messages": len(self._plugin._messages),
                    "returned_count": len(msgs),
                    "stats": {
                        "llm_input_tokens": total_llm_in,
                        "llm_output_tokens": total_llm_out,
                        "total_llm_tokens": total_llm_in + total_llm_out,
                        "total_llm_calls": sum(1 for m in msgs if m.event_type == "llm_call"),
                        "total_tool_calls": total_tool_calls,
                        "tool_success": tool_success,
                        "tool_failure": tool_fail,
                    },
                    "messages": [m.to_dict() for m in msgs],
                },
                summary=summary,
            )
