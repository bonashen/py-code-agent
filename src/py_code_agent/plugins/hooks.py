"""Plugin hooks specifications using pluggy."""

from typing import Any, Dict, List, Optional, Type

import pluggy

from py_code_agent.tools.base import BaseTool

hookspec = pluggy.HookspecMarker("py_code_agent")
hookimpl = pluggy.HookimplMarker("py_code_agent")


class ToolHooks:
    """Tool-related plugin hooks."""

    @hookspec
    def register_tools(self) -> List[BaseTool]:
        """Register one or more tools. Return empty list if no tools."""

    @hookspec
    def before_tool_execute(self, tool_name: str, arguments: Dict[str, Any]) -> None:
        """Called before a tool is executed."""

    @hookspec
    def after_tool_execute(
        self, tool_name: str, arguments: Dict[str, Any], result: Any
    ) -> None:
        """Called after a tool is executed. 'result' is the raw tool data dict."""

    @hookspec
    def enhance_tool_error(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        error_info: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Called when a tool execution fails. Return structured error enhancement.

        Called after tool execution if result["success"] is False.

        Priority: Lower number = higher priority. First non-None result wins.

        Args:
            tool_name: Name of the tool that failed.
            arguments: Tool arguments that were passed.
            error_info: Contains error classification and recovery guidance.
                - error_type: "missing_dependency" | "wrong_tool" | "permission_denied"
                             | "invalid_arguments" | "execution_error" | "unknown"
                - error: The raw error message string.
                - diagnosis: Human-readable analysis of what went wrong.
                - suggestions: List of concrete fix suggestions for the LLM.

        Returns:
            Dict with enhanced error information to inject into the LLM session:
                - error_type: Matched or refined error type string.
                - diagnosis: Detailed explanation of root cause.
                - fix_suggestions: Ordered list of actionable steps to recover.
                - confidence: 0.0-1.0, how confident the plugin is in this diagnosis.
            Return None or empty dict to skip enhancement (pass through raw error).
        """

    @hookspec
    def enhance_tool_error_priority(self) -> int:
        """Return priority for enhance_tool_error. Lower = higher priority.
        
        Default: 100. Common priorities:
        - 10: plan_plugin (planning errors)
        - 20: skills_plugin (skill workflow errors)
        - 30: mcp_plugin (MCP errors)
        - 100: default
        """


class AgentHooks:
    """Agent lifecycle hooks."""

    @hookspec
    def on_agent_start(self, input: str) -> None:
        """Called when agent starts processing input."""

    @hookspec
    def on_agent_end(self) -> None:
        """Called when agent finishes."""

    @hookspec
    def on_llm_call(
        self, messages: List[Dict[str, str]], tools: List[Dict[str, Any]]
    ) -> None:
        """Called before each LLM API call."""

    @hookspec
    def on_llm_response(self, response: Any) -> None:
        """Called after each LLM API response (streaming chunk)."""

    @hookspec
    def get_system_prompt(self) -> str:
        """Return additional system prompt content to inject into the agent.

        Plugins can contribute context-specific guidance, role definitions, or
        behavioral instructions. Content is appended to the base system prompt.
        Return empty string if no contribution.
        """

    @hookspec
    def on_plugin_heartbeat(
        self,
        event: str,
        data: Dict[str, Any],
    ) -> None:
        """Called when a plugin emits a heartbeat event.

        All plugins use this unified interface to emit heartbeat events.
        The plugin name is automatically inferred from the plugin class name.

        Unified event format (for external consumers):
        {
            "event_type": "plugin_heartbeat",
            "event": "scored",           // specific event
            "plugin_name": "plan",       // which plugin
            "plugin_id": "plan-001",     // plugin instance ID
            "data": { ... }              // event-specific data
        }

        Common events across plugins:
        - "loaded": Plugin loaded successfully
        - "updated": Plugin configuration updated
        - "started": Operation started
        - "completed": Operation completed
        - "failed": Operation failed
        - "retry": Operation retry

        Plugin-specific events:
        - PlanPlugin: "generated", "scored", "execute_started", "execute_completed",
                      "subtask_started", "subtask_completed", "subtask_retry",
                      "subtask_failed", "deadlock"
        - SoulPlugin: "loaded", "updated"
        - SkillsPlugin: "loaded", "skill_invoked", "skill_executed"
        """

    @hookspec
    def get_capabilities(self) -> Dict[str, Any]:
        """Return plugin capabilities for LLM to understand what this plugin provides.

        Returns:
            Dict with:
            - name: Plugin name
            - description: What this plugin does
            - tools: List of tool names this plugin provides
            - keywords: Keywords for matching user tasks
        """


PLUGIN_DISCOVERY_PROMPT = """You are a plugin recommendation assistant. Given a user task and available plugins, recommend which plugins should be loaded.

AVAILABLE PLUGINS:
{plugins}

USER TASK: {task}

Analyze the task and recommend which plugins would be helpful. Return a JSON array of plugin names to load.

Consider:
- Does the task involve planning? → load plan plugin
- Does the task involve skills/workflows? → load skills plugin
- Does the task involve Git operations? → load git plugin
- Does the task involve file context? → load context plugin

Return only the plugin names as a JSON array, e.g.:
["plan", "skills", "context"]

If no plugins are needed, return: []"""
