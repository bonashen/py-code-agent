"""Test ReAct (Reasoning + Acting) pattern in PlanPlugin subtask execution."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

_repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(_repo_root))

from plugins.builtin.plan_plugin import PlanPlugin, SubTask


def _make_plan_plugin() -> tuple[PlanPlugin, MagicMock]:
    """Create a PlanPlugin with a mocked agent reference."""
    plugin = PlanPlugin()
    mock_agent = MagicMock()
    mock_agent.tools = {}
    mock_agent.llm = MagicMock()
    mock_agent.config = None
    plugin.set_agent(mock_agent)
    return plugin, mock_agent


class TestReActParsing:
    """Test ReAct response parsing."""

    def test_parse_react_response_with_thought_and_action(self):
        """Parse a ReAct response with explicit Thought and Action."""
        plugin, _ = _make_plan_plugin()
        content = """Thought: I need to read the file first to understand the structure.
Then I can analyze it and provide recommendations.

Action: read_file({"path": "/tmp/test.txt"})"""

        thought, action, tool_calls = plugin._parse_react_response(content)

        assert "I need to read the file" in thought
        assert "read_file" in action
        assert len(tool_calls) == 1
        assert tool_calls[0]["function"]["name"] == "read_file"

    def test_parse_react_response_final_answer(self):
        """Parse a ReAct response with final answer (no tool call)."""
        plugin, _ = _make_plan_plugin()
        content = """Thought: Based on my analysis, the file contains 42 lines of code.
The main function is well-structured.

Action: The file has 42 lines with a well-structured main function."""

        thought, action, tool_calls = plugin._parse_react_response(content)

        assert "Based on my analysis" in thought
        assert "42 lines" in action
        assert len(tool_calls) == 0  # No tool calls for final answer

    def test_parse_react_response_without_format(self):
        """Parse a response that doesn't follow ReAct format."""
        plugin, _ = _make_plan_plugin()
        content = "Just a simple response without Thought or Action."

        thought, action, tool_calls = plugin._parse_react_response(content)

        assert thought == ""
        assert action == ""
        assert len(tool_calls) == 0

    def test_parse_react_response_with_multiple_tool_calls(self):
        """Parse a ReAct response with multiple tool calls in the action."""
        plugin, _ = _make_plan_plugin()
        content = """Thought: I need to read multiple files.

Action: [
  {"name": "read_file", "arguments": "{\\\"path\\\": \\"/tmp/file1.txt\\\"}"},
  {"name": "read_file", "arguments": "{\\\"path\\\": \\"/tmp/file2.txt\\\"}"}
]"""

        thought, action, tool_calls = plugin._parse_react_response(content)

        assert "multiple files" in thought
        assert len(tool_calls) == 2
        assert tool_calls[0]["function"]["name"] == "read_file"


class TestReActExecution:
    """Test ReAct execution in _run_subtask."""

    @pytest.mark.asyncio
    async def test_react_mode_uses_thought_action_format(self):
        """Verify that the system prompt instructs ReAct format."""
        plugin, mock_agent = _make_plan_plugin()
        mock_agent.tools = {}
        mock_agent.llm.complete = AsyncMock(return_value=MagicMock(
            content="Thought: I understand the task.\nAction: Done!",
            tool_calls=[],
        ))
        mock_agent.config = None

        subtask = SubTask(id="st1", title="Test", description="Test subtask")
        ok, result = await plugin._run_subtask(subtask, mock_agent)

        # Verify the system prompt includes ReAct instructions
        call_args = mock_agent.llm.complete.call_args
        messages = call_args[0][0] if call_args[0] else call_args[1].get("messages", [])
        system_msg = next((m for m in messages if getattr(m, "role", "") == "system"), None)
        
        if system_msg:
            content = getattr(system_msg, "content", "")
            assert "Thought:" in content
            assert "Action:" in content
            assert "ReAct" in content

    @pytest.mark.asyncio
    async def test_react_parsing_executes_tool_call(self):
        """Test that ReAct Action with tool call gets executed."""
        plugin, mock_agent = _make_plan_plugin()
        
        mock_tool = MagicMock()
        mock_tool.execute = AsyncMock(return_value=MagicMock(summary="File contents here"))
        mock_agent.tools = {"read_file": mock_tool}
        
        # Simulate multi-turn ReAct: first call has tool, second call has final answer
        call_count = [0]
        async def multiturn_react(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return {
                    "content": 'Thought: I need to read the file.\nAction: read_file({"path": "/tmp/test.txt"})',
                    "tool_calls": [],
                }
            else:
                return {
                    "content": 'Thought: The file has been read.\nAction: File contents here',
                    "tool_calls": [],
                }
        
        mock_agent.llm.complete = multiturn_react
        mock_agent.config = None

        subtask = SubTask(id="st1", title="Read file", description="Read a file")
        ok, result = await plugin._run_subtask(subtask, mock_agent)

        assert ok is True
        assert "read_file" in result or "File" in result
        mock_tool.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_react_final_answer_no_tool(self):
        """Test that ReAct Action with final answer returns without tool execution."""
        plugin, mock_agent = _make_plan_plugin()
        mock_agent.tools = {}
        
        # Single-turn ReAct with final answer
        call_count = [0]
        async def single_turn_react(*args, **kwargs):
            call_count[0] += 1
            return {
                "content": 'Thought: The task is simple.\nAction: The answer is 42.',
                "tool_calls": [],
            }
        
        mock_agent.llm.complete = single_turn_react
        mock_agent.config = None

        subtask = SubTask(id="st1", title="Answer", description="Provide answer")
        ok, result = await plugin._run_subtask(subtask, mock_agent)

        assert ok is True
        assert "42" in result

    @pytest.mark.asyncio
    async def test_react_multiturn_with_observation(self):
        """Test ReAct multi-turn execution with Thought-Action-Observation cycle."""
        plugin, mock_agent = _make_plan_plugin()
        
        mock_tool = MagicMock()
        mock_tool.execute = AsyncMock(return_value=MagicMock(summary="Line count: 42"))
        mock_agent.tools = {"count_lines": mock_tool}
        
        call_count = [0]
        async def multiturn_complete(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return {
                    "content": 'Thought: I need to count the lines first.\nAction: count_lines({"file": "/tmp/data.txt"})',
                    "tool_calls": [],
                }
            else:
                return {
                    "content": 'Thought: Now I have the line count.\nAction: The file has 42 lines.',
                    "tool_calls": [],
                }
        
        mock_agent.llm.complete = multiturn_complete
        mock_agent.config = None

        subtask = SubTask(id="st1", title="Count lines", description="Count lines in file")
        ok, result = await plugin._run_subtask(subtask, mock_agent)

        assert ok is True
        assert "42" in result
        assert call_count[0] == 2
        mock_tool.execute.assert_called_once()
