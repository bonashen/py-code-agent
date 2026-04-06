"""Test ReAct mode in the master Agent."""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

_repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(_repo_root))

from py_code_agent.config.models import Config, ReActConfig
from py_code_agent.core.agent import Agent


def _make_agent(react_enabled: bool = False) -> Agent:
    config = Config()
    config.react = ReActConfig(enabled=react_enabled, max_turns=50)
    agent = Agent.__new__(Agent)
    agent.config = config
    agent.agent_id = "test-agent"
    agent.session = MagicMock()
    agent.session.messages = []
    agent.session.add_message = MagicMock()
    agent.tools = {}
    agent.plugin_manager = None
    return agent


class TestReActConfig:
    def test_react_config_defaults(self):
        config = ReActConfig()
        assert config.enabled is False
        assert config.max_turns == 50

    def test_react_config_enabled(self):
        config = ReActConfig(enabled=True, max_turns=100)
        assert config.enabled is True
        assert config.max_turns == 100


class TestAgentPrepareMessagesReAct:
    def test_system_prompt_normal_mode(self):
        agent = _make_agent(react_enabled=False)
        messages = agent._prepare_messages()
        system_msg = messages[0]
        assert system_msg.role == "system"
        assert "ReAct" not in system_msg.content
        assert "helpful AI coding assistant" in system_msg.content

    def test_system_prompt_react_mode(self):
        agent = _make_agent(react_enabled=True)
        messages = agent._prepare_messages()
        system_msg = messages[0]
        assert system_msg.role == "system"
        assert "ReAct" in system_msg.content
        assert "Thought:" in system_msg.content
        assert "Action:" in system_msg.content
        assert "Observation:" in system_msg.content


class TestAgentParseReActResponse:
    def test_parse_react_with_thought_and_action(self):
        agent = _make_agent()
        content = """Thought: I need to read the file first.
Then I can analyze it.

Action: read_file({"path": "/tmp/test.txt"})"""

        thought, action, tool_calls = agent._parse_react_response(content)

        assert "read the file" in thought
        assert "read_file" in action
        assert len(tool_calls) == 1
        assert tool_calls[0]["function"]["name"] == "read_file"

    def test_parse_react_final_answer(self):
        agent = _make_agent()
        content = """Thought: Based on my analysis, the answer is 42.

Action: The answer is 42."""

        thought, action, tool_calls = agent._parse_react_response(content)

        assert "answer is 42" in thought
        assert "42" in action
        assert len(tool_calls) == 0

    def test_parse_react_without_format(self):
        agent = _make_agent()
        content = "This is just a regular response without any format."

        thought, action, tool_calls = agent._parse_react_response(content)

        assert thought == ""
        assert action == ""
        assert len(tool_calls) == 0

    def test_parse_react_with_json_array_tool_calls(self):
        agent = _make_agent()
        content = """Thought: I need to call multiple tools.

Action: [{"name": "tool1", "arguments": "{}"}, {"name": "tool2", "arguments": "{}"}]"""

        thought, action, tool_calls = agent._parse_react_response(content)

        assert "multiple tools" in thought
        assert len(tool_calls) == 2
        assert tool_calls[0]["function"]["name"] == "tool1"
        assert tool_calls[1]["function"]["name"] == "tool2"

    def test_parse_react_with_observation(self):
        agent = _make_agent()
        content = """Thought: I executed the tool.
Action: read_file({"path": "/test.txt"})
Observation: File contents here"""

        thought, action, tool_calls = agent._parse_react_response(content)

        assert "executed" in thought
        assert "read_file" in action
        assert "Observation" not in action
        assert len(tool_calls) == 1


class TestAgentReActIntegration:
    @pytest.mark.asyncio
    async def test_react_mode_uses_thought_action_format(self):
        agent = _make_agent(react_enabled=True)
        agent.session.messages = []

        messages = agent._prepare_messages()
        system_msg = messages[0]
        assert "ReAct" in system_msg.content
        assert "Thought:" in system_msg.content
        assert "Action:" in system_msg.content

    @pytest.mark.asyncio
    async def test_react_mode_disabled_uses_normal_format(self):
        agent = _make_agent(react_enabled=False)
        agent.session.messages = []

        messages = agent._prepare_messages()
        system_msg = messages[0]
        assert "ReAct" not in system_msg.content
        assert "helpful AI coding assistant" in system_msg.content


def _make_tool_def(params: list) -> MagicMock:
    """Build a mock ToolDefinition with typed parameters."""
    mock_def = MagicMock()
    mock_def.parameters = params
    return mock_def


class TestValidateToolArguments:
    def test_validates_missing_required_param(self):
        agent = _make_agent()

        path_param = MagicMock()
        path_param.name = "path"
        path_param.type = MagicMock(value="string")
        path_param.required = True
        path_param.default = None

        content_param = MagicMock()
        content_param.name = "content"
        content_param.type = MagicMock(value="string")
        content_param.required = True
        content_param.default = None

        mock_tool = MagicMock()
        mock_tool.definition = _make_tool_def([path_param, content_param])
        agent.tools = {"write_file": mock_tool}

        err = agent._validate_tool_arguments("write_file", {"path": "/tmp/test.txt"})
        assert err is not None
        assert "Missing required parameter 'content'" in err
        assert "write_file" in err

    def test_validates_wrong_type_string_vs_dict(self):
        agent = _make_agent()

        path_param = MagicMock()
        path_param.name = "path"
        path_param.type = MagicMock(value="string")
        path_param.required = True
        path_param.default = None

        mock_tool = MagicMock()
        mock_tool.definition = _make_tool_def([path_param])
        agent.tools = {"write_file": mock_tool}

        err = agent._validate_tool_arguments("write_file", {"path": {"nested": "value"}})
        assert err is not None
        assert "expected string but got dict" in err
        assert "Example:" in err

    def test_validates_wrong_type_integer_vs_string(self):
        agent = _make_agent()

        limit_param = MagicMock()
        limit_param.name = "limit"
        limit_param.type = MagicMock(value="integer")
        limit_param.required = True
        limit_param.default = None

        mock_tool = MagicMock()
        mock_tool.definition = _make_tool_def([limit_param])
        agent.tools = {"search": mock_tool}

        err = agent._validate_tool_arguments("search", {"limit": "not a number"})
        assert err is not None
        assert "expected integer but got str" in err

    def test_validates_boolean_type(self):
        agent = _make_agent()

        recursive_param = MagicMock()
        recursive_param.name = "recursive"
        recursive_param.type = MagicMock(value="boolean")
        recursive_param.required = True
        recursive_param.default = None

        mock_tool = MagicMock()
        mock_tool.definition = _make_tool_def([recursive_param])
        agent.tools = {"walk_dir": mock_tool}

        err = agent._validate_tool_arguments("walk_dir", {"recursive": "yes"})
        assert err is not None
        assert "expected boolean but got str" in err

    def test_passes_non_strict_int_as_number(self):
        agent = _make_agent()

        count_param = MagicMock()
        count_param.name = "count"
        count_param.type = MagicMock(value="number")
        count_param.required = True
        count_param.default = None

        mock_tool = MagicMock()
        mock_tool.definition = _make_tool_def([count_param])
        agent.tools = {"count_tool": mock_tool}

        err = agent._validate_tool_arguments("count_tool", {"count": 5})
        assert err is None

    def test_skips_optional_with_default(self):
        agent = _make_agent()

        path_param = MagicMock()
        path_param.name = "path"
        path_param.type = MagicMock(value="string")
        path_param.required = False
        path_param.default = "/tmp/default.txt"

        mock_tool = MagicMock()
        mock_tool.definition = _make_tool_def([path_param])
        agent.tools = {"read": mock_tool}

        err = agent._validate_tool_arguments("read", {})
        assert err is None

    def test_returns_none_for_unknown_tool(self):
        agent = _make_agent()
        agent.tools = {}
        err = agent._validate_tool_arguments("unknown_tool", {})
        assert err is None

    def test_returns_none_for_tool_without_definition(self):
        agent = _make_agent()
        agent.tools = {"raw_tool": MagicMock()}
        err = agent._validate_tool_arguments("raw_tool", {})
        assert err is None

    def test_example_value_helper_string(self):
        agent = _make_agent()
        assert agent._example_value("string") == "hello world"

    def test_example_value_helper_integer(self):
        agent = _make_agent()
        assert agent._example_value("integer") == 42

    def test_example_value_helper_boolean(self):
        agent = _make_agent()
        assert agent._example_value("boolean") is True
