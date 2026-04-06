"""Test get_system_prompt() for all built-in plugins that implement it."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(_repo_root))


def _import_plugin(name: str):
    """Import a plugin module with litellm blocked."""
    blockers = ["litellm", "litellm.proxy", "litellm.proxy.proxy_logging"]
    for b in blockers:
        if b not in sys.modules:
            sys.modules[b] = type(sys)(b)
    import importlib
    return importlib.import_module(name)


class TestGitPluginSystemPrompt:
    def test_get_system_prompt(self):
        mod = _import_plugin("plugins.builtin.git_plugin")
        plugin = mod.GitStatusPlugin()
        result = plugin.get_system_prompt()
        assert isinstance(result, str)
        assert len(result) > 0
        assert "git" in result.lower()
        assert "git_status" in result


class TestSearchPluginSystemPrompt:
    def test_get_system_prompt(self):
        mod = _import_plugin("plugins.builtin.search_plugin")
        plugin = mod.SearchPlugin()
        result = plugin.get_system_prompt()
        assert isinstance(result, str)
        assert len(result) > 0
        assert "web_search" in result
        assert "search" in result.lower()


class TestSkillsPluginSystemPrompt:
    def test_get_system_prompt(self):
        mod = _import_plugin("plugins.builtin.skills_plugin")
        plugin = mod.ClaudeSkillsPlugin()
        result = plugin.get_system_prompt()
        assert isinstance(result, str)
        assert len(result) > 0
        assert "skill" in result.lower()
        assert "list_skills" in result
        assert "get_skill" in result

    def test_get_system_prompt_with_skills(self):
        mod = _import_plugin("plugins.builtin.skills_plugin")
        original = mod._discover_skills
        mod._discover_skills = MagicMock(return_value={
            "test-skill": {"name": "test-skill", "description": "A test skill", "content": "", "path": "/tmp", "files": []},
        })
        plugin = mod.ClaudeSkillsPlugin()
        plugin._ensure_loaded()
        result = plugin.get_system_prompt()
        assert "test-skill" in result
        mod._discover_skills = original

    def test_get_system_prompt_contains_workflow_rules(self):
        mod = _import_plugin("plugins.builtin.skills_plugin")
        plugin = mod.ClaudeSkillsPlugin()
        result = plugin.get_system_prompt()
        assert "How to Use a Retrieved Skill" in result
        assert "CRITICAL rules" in result
        assert "workflow steps IN ORDER \u2014" in result
        assert "Do NOT substitute with generic tools" in result

    def test_get_system_prompt_contains_naming_rules(self):
        mod = _import_plugin("plugins.builtin.skills_plugin")
        plugin = mod.ClaudeSkillsPlugin()
        result = plugin.get_system_prompt()
        assert "Skill Naming Rules" in result
        assert "skill_<name>" in result
        assert 'NOT `get_skill("skill_docx")`' in result

    def test_get_system_prompt_contains_hard_constraints(self):
        mod = _import_plugin("plugins.builtin.skills_plugin")
        plugin = mod.ClaudeSkillsPlugin()
        result = plugin.get_system_prompt()
        assert "Hard Constraints" in result
        assert "NEVER use `write_file` to create a .docx file" in result
        assert "raw text written to a .docx extension is NOT a valid .docx" in result
        assert "For .docx creation: use the docx skill" in result

    def test_get_system_prompt_contains_self_healing(self):
        mod = _import_plugin("plugins.builtin.skills_plugin")
        plugin = mod.ClaudeSkillsPlugin()
        result = plugin.get_system_prompt()
        assert "Skill Self-Healing" in result
        assert "command not found" in result
        assert "module not found" in result
        assert "execute_bash" in result
        assert "retry the original skill workflow" in result


class TestMCPGatewayPluginSystemPrompt:
    def test_get_system_prompt_no_servers(self):
        mod = _import_plugin("plugins.builtin.mcp_gateway_plugin")
        plugin = mod.MCPGatewayPlugin()
        plugin._tools = []
        result = plugin.get_system_prompt()
        assert isinstance(result, str)
        assert len(result) > 0
        assert "MCP" in result
        assert "No MCP servers" in result

    def test_get_system_prompt_with_tools(self):
        mod = _import_plugin("plugins.builtin.mcp_gateway_plugin")
        plugin = mod.MCPGatewayPlugin()
        # Create mock MCP tools
        mock_tool_1 = MagicMock()
        mock_tool_1.server_name = "filesystem"
        mock_tool_1.definition = MagicMock()
        mock_tool_1.definition.name = "mcp_filesystem_read"
        mock_tool_1.definition.description = "Read a file from the filesystem"

        mock_tool_2 = MagicMock()
        mock_tool_2.server_name = "filesystem"
        mock_tool_2.definition = MagicMock()
        mock_tool_2.definition.name = "mcp_filesystem_write"
        mock_tool_2.definition.description = "Write content to a file"

        plugin._tools = [mock_tool_1, mock_tool_2]

        result = plugin.get_system_prompt()
        assert "mcp_filesystem_read" in result
        assert "mcp_filesystem_write" in result
        assert "filesystem" in result
        assert "mcp_call_tool" in result
