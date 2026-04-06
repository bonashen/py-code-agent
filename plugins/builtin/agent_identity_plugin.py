"""Self-awareness plugin - loads agent.md for agent identity and system prompt."""

import os
from pathlib import Path
from typing import List, Optional

from py_code_agent.plugins.hooks import hookimpl
from py_code_agent.tools.base import BaseTool, ToolDefinition, ToolParameter, ToolParameterType, ToolResult


AGENT_MD_TEMPLATE = """# Py Code Agent - Self Description

You are **Py Code Agent**, an autonomous AI coding assistant.

## Identity

- **Name**: Py Code Agent
- **Type**: AI Coding Assistant
- **Platform**: Python CLI with LiteLLM
- **Author**: Py Code Agent Team
- **License**: MIT

## Core Capabilities

- **File Operations**: Read, write, edit files with path validation
- **Bash Execution**: Run shell commands with timeout and path controls
- **LLM Integration**: 100+ models via LiteLLM (OpenAI, Anthropic, Azure, Ollama, etc.)
- **Plugin System**: Extensible via pluggy hooks (tool, agent lifecycle, LLM events)
- **Streaming**: Real-time streaming responses via Server-Sent Events

## Built-in Tools

| Tool | Purpose |
|------|---------|
| `read_file` | Read file contents with optional line range |
| `write_file` | Write or append to files (path-validated) |
| `execute_bash` | Run shell commands with timeout |

## Behavioral Rules

1. **Path Safety**: Never access blocked paths (~/.ssh, ~/.aws). Always validate paths.
2. **Tool Feedback**: After executing tools, use results to inform next steps.
3. **Error Recovery**: If a tool fails, explain the error and suggest alternatives.
4. **Minimal Change**: Prefer targeted edits over wholesale rewrites.
5. **Confirmation**: For destructive operations (delete, overwrite), confirm first.
6. **Streaming**: Stream responses as they arrive for better UX.

## Communication Style

- Be concise and actionable
- Use code blocks for all code snippets
- Format output with tables/markdown when presenting structured data
- Admit limitations when uncertain

## Plugin System

The agent has a pluggy-based plugin system. Plugins can:
- Register new tools via `register_tools()` hook
- Intercept tool calls via `before_tool_execute()` / `after_tool_execute()`
- React to agent lifecycle via `on_agent_start()` / `on_agent_end()`
- Observe LLM calls via `on_llm_call()` / `on_llm_response()`

Plugins are loaded from `~/.claude/skills/` directories.
"""


class AgentIdentityPlugin:
    """Loads agent.md to configure agent identity and system prompt."""

    def __init__(self):
        self._agent_md_content: Optional[str] = None
        self._agent_md_path: Optional[Path] = None

    @hookimpl
    def on_agent_start(self, input: str) -> None:
        self._load_agent_md()

    def _load_agent_md(self) -> Optional[str]:
        paths_to_try = [
            Path.cwd() / ".py-code-agent" / "agent.md",
            Path.home() / ".config" / "py-code-agent" / "agent.md",
            Path.home() / ".claude" / "agent.md",
        ]

        for p in paths_to_try:
            if p.exists():
                try:
                    self._agent_md_content = p.read_text(encoding="utf-8")
                    self._agent_md_path = p
                    return self._agent_md_content
                except Exception:
                    pass

        self._agent_md_content = AGENT_MD_TEMPLATE
        self._agent_md_path = paths_to_try[-1]
        return None

    @hookimpl
    def register_tools(self) -> List[BaseTool]:
        return [GetAgentIdentityTool(self), ReloadAgentMdTool(self)]

    def get_identity_content(self) -> str:
        if self._agent_md_content is None:
            self._load_agent_md()
        return self._agent_md_content or AGENT_MD_TEMPLATE

    def reload(self) -> str:
        self._agent_md_content = None
        return self._load_agent_md() or AGENT_MD_TEMPLATE


class GetAgentIdentityTool(BaseTool):
    """Get the agent's identity and system prompt from agent.md."""

    def __init__(self, plugin: AgentIdentityPlugin):
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="get_agent_identity",
            description="Returns the agent's identity, capabilities, and behavioral rules defined in agent.md. Call this to understand who you are and what you can do.",
            parameters=[],
        )

    async def execute(self, **kwargs) -> ToolResult:
        content = self._plugin.get_identity_content()
        return ToolResult.ok(
            data={"content": content},
            summary="Returned agent identity from agent.md",
        )


class ReloadAgentMdTool(BaseTool):
    """Reload agent.md from disk (useful after editing the file)."""

    def __init__(self, plugin: AgentIdentityPlugin):
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="reload_agent_md",
            description="Reload the agent.md file from disk, refreshing the agent's identity and system prompt without restarting.",
            parameters=[],
        )

    async def execute(self, **kwargs) -> ToolResult:
        content = self._plugin.reload()
        path = self._plugin._agent_md_path
        return ToolResult.ok(
            data={"content": content, "path": str(path) if path else None},
            summary=f"Reloaded agent.md from {path}",
        )
