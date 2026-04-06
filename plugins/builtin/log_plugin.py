"""Logging plugin - logs all tool calls and agent events."""

import logging
from datetime import datetime
from typing import Any, Dict, List

from py_code_agent.plugins.hooks import hookimpl
from py_code_agent.tools.base import BaseTool, ToolDefinition, ToolParameter, ToolParameterType, ToolResult

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class LogPlugin:
    """Plugin that logs all tool executions and agent lifecycle events."""

    def __init__(self) -> None:
        self.log: List[Dict[str, Any]] = []

    @hookimpl
    def register_tools(self) -> List[BaseTool]:
        return [GetLogTool(self)]

    @hookimpl
    def on_agent_start(self, input: str) -> None:
        entry = {"time": datetime.now().isoformat(), "event": "agent_start", "input": input}
        self.log.append(entry)
        logger.info("[LogPlugin] Agent started: %s", input[:50])

    @hookimpl
    def on_agent_end(self) -> None:
        entry = {"time": datetime.now().isoformat(), "event": "agent_end"}
        self.log.append(entry)
        logger.info("[LogPlugin] Agent ended")

    @hookimpl
    def before_tool_execute(self, tool_name: str, arguments: Dict[str, Any]) -> None:
        entry = {"time": datetime.now().isoformat(), "event": "tool_before", "tool": tool_name}
        self.log.append(entry)
        logger.info("[LogPlugin] Tool BEFORE: %s(%s)", tool_name, arguments)

    @hookimpl
    def after_tool_execute(
        self, tool_name: str, arguments: Dict[str, Any], result: Any
    ) -> None:
        success = result.get("success", False) if isinstance(result, dict) else False
        error = result.get("error") if isinstance(result, dict) else None
        entry = {
            "time": datetime.now().isoformat(),
            "event": "tool_after",
            "tool": tool_name,
            "success": success,
            "error": error,
        }
        self.log.append(entry)
        if success:
            logger.info("[LogPlugin] Tool AFTER: %s success=True", tool_name)
        else:
            logger.info("[LogPlugin] Tool AFTER: %s success=False error=%s", tool_name, error)

    @hookimpl
    def on_plugin_heartbeat(
        self,
        event: str,
        data: Dict[str, Any],
    ) -> None:
        plugin_name = data.get("plugin_name", "unknown")
        plugin_id = data.get("plugin_id", "")
        entry = {
            "time": datetime.now().isoformat(),
            "event": "plugin_heartbeat",
            "plugin_event": event,
            "plugin_name": plugin_name,
            "plugin_id": plugin_id,
            "data": {k: v for k, v in data.items() if k not in ("plugin_name", "plugin_id")},
        }
        self.log.append(entry)
        logger.info("[LogPlugin] Plugin heartbeat: %s.%s -> %s", plugin_name, event, data)


class GetLogTool(BaseTool):
    """Retrieve the tool execution log recorded by LogPlugin."""

    def __init__(self, plugin: LogPlugin):
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="get_tool_log",
            description="Get the log of all tool calls and agent events recorded by the logging plugin",
            parameters=[],
        )

    async def execute(self, **kwargs) -> ToolResult:
        log = self._plugin.log
        return ToolResult.ok(
            data={"log": log, "count": len(log)},
            summary=f"Returned {len(log)} log entries",
        )
