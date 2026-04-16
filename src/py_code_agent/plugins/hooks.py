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


# === Extended Hooks (对标 pi-coding-agent) ===

class StreamingHooks:
    """Message and tool streaming hooks."""

    @hookspec
    def on_message_start(self, message_id: str) -> None:
        """Called when a new assistant message starts."""

    @hookspec
    def on_message_update(self, token: str, accumulated: str, message_id: str) -> None:
        """Called for each token in streaming response."""

    @hookspec
    def on_message_end(self, content: str, message_id: str) -> None:
        """Called when assistant message streaming completes."""

    @hookspec
    def on_tool_execution_start(self, tool_name: str, arguments: Dict[str, Any], tool_call_id: str) -> None:
        """Called when tool execution starts."""

    @hookspec
    def on_tool_execution_update(self, tool_name: str, output: str, tool_call_id: str) -> None:
        """Called for streaming tool output (e.g., bash stdout)."""

    @hookspec
    def on_tool_execution_end(self, tool_name: str, result: Any, tool_call_id: str) -> None:
        """Called when tool execution completes."""


class SessionHooks:
    """Session management hooks."""

    @hookspec
    def on_session_before_compact(self, messages: List[Dict]) -> Optional[List[Dict]]:
        """Called before session compaction. Can return custom compacted messages."""

    @hookspec
    def on_session_compacted(self, compacted_messages: List[Dict]) -> None:
        """Called after session compaction."""

    @hookspec
    def on_session_fork(self, from_node_id: str, new_session_id: str) -> None:
        """Called when session is forked."""

    @hookspec
    def on_session_switch(self, old_node_id: str, new_node_id: str) -> None:
        """Called when switching to a different session node."""

    @hookspec
    def on_session_tree(self, tree_structure: Dict) -> None:
        """Called when session tree is accessed."""


class ModelHooks:
    """Model selection and context hooks."""

    @hookspec
    def on_model_select(self, old_model: str, new_model: str, source: str) -> None:
        """Called when model is switched (source: user/auto/fallback)."""

    @hookspec
    def on_context_access(self, messages: List[Dict]) -> Optional[List[Dict]]:
        """Called when accessing context. Can filter/trim messages."""


class TurnHooks:
    """Agent turn hooks."""

    @hookspec
    def on_turn_start(self, turn_number: int, input: str) -> None:
        """Called at the start of each agent turn."""

    @hookspec
    def on_turn_end(self, turn_number: int, output: str) -> None:
        """Called at the end of each agent turn."""


class ExtensionHooks:
    """Extension registration hooks (对标 pi-coding-agent ExtensionAPI)."""

    @hookspec
    def register_commands(self) -> List[Dict[str, Any]]:
        """Register slash commands. Return list of command definitions.
        
        Command definition format:
        {
            "name": "fork",
            "description": "Create a branch from current session",
            "handler": callable,
            "parameters": [...]
        }
        """

    @hookspec
    def register_shortcuts(self) -> List[Dict[str, Any]]:
        """Register keyboard shortcuts.
        
        Shortcut definition format:
        {
            "key": "ctrl+p",
            "description": "Cycle models",
            "handler": callable
        }
        """

    @hookspec
    def register_cli_flags(self) -> List[Dict[str, Any]]:
        """Register CLI flags.
        
        Flag definition format:
        {
            "name": "--verbose",
            "type": bool,
            "default": False,
            "description": "Enable verbose output"
        }
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
