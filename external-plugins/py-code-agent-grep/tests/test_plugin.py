"""Tests for GrepPlugin integration."""

from __future__ import annotations

from py_code_agent_grep.plugin import GrepPlugin
from py_code_agent_grep.tools import GrepCountTool, GrepSearchTool


class TestGrepPlugin:
    def test_register_tools(self):
        plugin = GrepPlugin()
        tools = plugin.register_tools()
        assert len(tools) == 2
        assert isinstance(tools[0], GrepSearchTool)
        assert isinstance(tools[1], GrepCountTool)

    def test_get_system_prompt(self):
        plugin = GrepPlugin()
        prompt = plugin.get_system_prompt()
        assert "grep_search" in prompt
        assert "grep_count" in prompt
        assert "AST" in prompt
        assert "Text mode" in prompt

    def test_enhance_tool_error_regex(self):
        plugin = GrepPlugin()
        result = plugin.enhance_tool_error(
            "grep_search",
            {"pattern": "[invalid"},
            {"error": "Invalid regex pattern"},
        )
        assert result is not None
        assert result["error_type"] == "grep_invalid_regex"
        assert result["confidence"] == 0.95

    def test_enhance_tool_error_ast(self):
        plugin = GrepPlugin()
        result = plugin.enhance_tool_error(
            "grep_search",
            {"pattern": "def $F($$$):"},
            {"error": "AST parse error"},
        )
        assert result is not None
        assert result["error_type"] == "grep_ast_parse_error"

    def test_enhance_tool_error_no_matches(self):
        plugin = GrepPlugin()
        result = plugin.enhance_tool_error(
            "grep_search",
            {"pattern": "ZZZZ"},
            {"error": "No matches found"},
        )
        assert result is not None
        assert result["error_type"] == "grep_no_matches"

    def test_enhance_tool_error_unrelated(self):
        plugin = GrepPlugin()
        result = plugin.enhance_tool_error(
            "other_tool",
            {},
            {"error": "some error"},
        )
        assert result is None

    def test_error_priority(self):
        plugin = GrepPlugin()
        assert plugin.enhance_tool_error_priority() == 50
