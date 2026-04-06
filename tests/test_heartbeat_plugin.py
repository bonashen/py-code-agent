"""Test HeartbeatPlugin — agent activity heartbeat aggregation."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

_repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(_repo_root))

from plugins.builtin.heartbeat_plugin import HeartbeatMessage, HeartbeatPlugin


def _make_hb() -> HeartbeatPlugin:
    plugin = HeartbeatPlugin()
    plugin._session_id = "test-session"
    plugin._session_start = 1000.0
    plugin._sequence = 0
    plugin._active = True  # simulate active session
    return plugin


class TestHeartbeatMessage:
    def test_heartbeat_message_to_dict(self):
        msg = HeartbeatMessage(
            id="msg1",
            timestamp=1234.5,
            event_type="llm_call",
            session_id="s1",
            sequence=1,
            llm_input_tokens=10,
            llm_output_tokens=20,
            llm_tool_calls=2,
            tool_name="read_file",
            tool_duration_ms=150.5,
            tool_success=True,
            tool_error="",
            message_count=3,
            active_tools=["read_file", "write_file"],
            extra={"subtask_id": "st1"},
        )
        d = msg.to_dict()
        assert d["id"] == "msg1"
        assert d["event_type"] == "llm_call"
        assert d["llm_input_tokens"] == 10
        assert d["llm_output_tokens"] == 20
        assert d["llm_tool_calls"] == 2
        assert d["tool_name"] == "read_file"
        assert d["tool_duration_ms"] == 150.5
        assert d["tool_success"] is True
        assert d["extra"]["subtask_id"] == "st1"

    def test_heartbeat_message_defaults(self):
        msg = HeartbeatMessage(id="m1", timestamp=1.0, event_type="agent_start")
        assert msg.session_id == ""
        assert msg.sequence == 0
        assert msg.llm_input_tokens == 0
        assert msg.tool_success is True
        assert msg.extra == {}


class TestHeartbeatPluginAppend:
    def test_append_increments_sequence(self):
        plugin = _make_hb()
        plugin._append("agent_start")
        plugin._append("agent_end")
        assert plugin._sequence == 2
        assert len(plugin._messages) == 2

    def test_append_rolling_buffer(self):
        plugin = _make_hb()
        plugin._max_buffer = 3
        for i in range(5):
            plugin._append(f"event_{i}", extra={"i": i})
        assert len(plugin._messages) == 3
        assert plugin._messages[0].extra["i"] == 2
        assert plugin._messages[1].extra["i"] == 3
        assert plugin._messages[2].extra["i"] == 4

    def test_append_ignores_when_disabled(self):
        plugin = _make_hb()
        plugin._enabled = False
        plugin._append("llm_call")
        assert len(plugin._messages) == 0

    def test_append_extra_fields(self):
        plugin = _make_hb()
        plugin._append("llm_call", subtask_id="st1", turn=3)
        msg = plugin._messages[0]
        assert msg.extra["subtask_id"] == "st1"
        assert msg.extra["turn"] == 3


class TestHeartbeatPluginHooks:
    def test_on_agent_start_resets_state(self):
        plugin = _make_hb()
        plugin._messages = [MagicMock()]
        plugin._sequence = 99
        plugin._active = True
        plugin.on_agent_start("test input")
        assert plugin._active is True
        # sequence was reset to 0 then incremented by _append in on_agent_start
        assert plugin._sequence == 1
        assert len(plugin._messages) == 1
        assert plugin._session_id != "test-session"

    def test_on_agent_end_sets_inactive(self):
        plugin = _make_hb()
        plugin._active = True
        plugin._session_start = plugin._session_start  # keep as-is
        plugin.on_agent_end()
        assert plugin._active is False
        assert len(plugin._messages) == 1
        assert plugin._messages[0].event_type == "agent_end"

    def test_on_llm_call_appends_event(self):
        plugin = _make_hb()
        tools = [
            {"function": {"name": "read_file"}},
            {"function": {"name": "write_file"}},
        ]
        plugin.on_llm_call(
            [{"role": "user", "content": "hello"}],
            tools,
        )
        assert len(plugin._messages) == 1
        msg = plugin._messages[0]
        assert msg.event_type == "llm_call"
        assert msg.message_count == 1
        assert msg.active_tools == ["read_file", "write_file"]

    def test_on_llm_response_dict_response(self):
        plugin = _make_hb()
        resp = MagicMock()
        resp.get = lambda k, d=None: {
            "usage": {"prompt_tokens": 5, "completion_tokens": 10},
            "tool_calls": [{"id": "tc1"}, {"id": "tc2"}],
        }.get(k, d)
        plugin.on_llm_response(resp)
        assert len(plugin._messages) == 1
        msg = plugin._messages[0]
        assert msg.event_type == "llm_response"
        assert msg.llm_input_tokens == 5
        assert msg.llm_output_tokens == 10
        assert msg.llm_tool_calls == 2

    def test_before_tool_execute_starts_timer(self):
        plugin = _make_hb()
        plugin.before_tool_execute("read_file", {"path": "/tmp/test"})
        assert "read_file" in plugin._tool_timers
        assert len(plugin._messages) == 1
        assert plugin._messages[0].event_type == "tool_before"
        assert plugin._messages[0].tool_name == "read_file"

    def test_after_tool_execute_records_duration(self):
        plugin = _make_hb()
        plugin._tool_timers["read_file"] = 1000.0
        result = MagicMock()
        result.is_success = MagicMock(return_value=True)
        plugin.after_tool_execute("read_file", {"path": "/tmp/test"}, result)
        msg = plugin._messages[0]
        assert msg.event_type == "tool_after"
        assert msg.tool_name == "read_file"
        assert msg.tool_duration_ms > 0
        assert msg.tool_success is True

    def test_after_tool_execute_failure(self):
        plugin = _make_hb()
        plugin._tool_timers["read_file"] = 1000.0
        result = MagicMock()
        result.is_success = MagicMock(return_value=False)
        result.error = "File not found"
        plugin.after_tool_execute("read_file", {}, result)
        msg = plugin._messages[0]
        assert msg.tool_success is False
        assert "not found" in msg.tool_error


class TestGetHeartbeatStatusTool:
    @pytest.mark.asyncio
    async def test_get_heartbeat_status_empty(self):
        plugin = _make_hb()
        tool = plugin.GetHeartbeatStatusTool(plugin=plugin)
        result = await tool.execute(limit=10)
        assert result.success
        data = result.data
        assert data["active"] is True
        assert data["returned_count"] == 0
        assert data["stats"]["total_llm_calls"] == 0

    @pytest.mark.asyncio
    async def test_get_heartbeat_status_with_events(self):
        plugin = _make_hb()
        plugin._append("llm_call", message_count=3, active_tools=["read"])
        plugin._append("llm_response", llm_input_tokens=5, llm_output_tokens=10)
        plugin._append("tool_before", tool_name="read_file")
        plugin._append("tool_after", tool_name="read_file", duration_ms=50.0, success=True)

        tool = plugin.GetHeartbeatStatusTool(plugin=plugin)
        result = await tool.execute(limit=10)
        assert result.success
        data = result.data
        assert data["returned_count"] == 4
        assert data["stats"]["llm_input_tokens"] == 5
        assert data["stats"]["llm_output_tokens"] == 10
        assert data["stats"]["total_llm_calls"] == 1
        assert data["stats"]["total_tool_calls"] == 2
        assert data["stats"]["tool_success"] == 1
        assert data["stats"]["tool_failure"] == 0

    @pytest.mark.asyncio
    async def test_filter_by_event_type(self):
        plugin = _make_hb()
        plugin._append("llm_call")
        plugin._append("llm_response")
        plugin._append("tool_after", tool_name="read_file")
        plugin._append("tool_after", tool_name="write_file")

        tool = plugin.GetHeartbeatStatusTool(plugin=plugin)
        result = await tool.execute(event_type="tool_after")
        data = result.data
        assert data["returned_count"] == 2
        for msg in data["messages"]:
            assert msg["event_type"] == "tool_after"

    @pytest.mark.asyncio
    async def test_limit_respected(self):
        plugin = _make_hb()
        for i in range(20):
            plugin._append(f"event_{i}", extra={"i": i})
        tool = plugin.GetHeartbeatStatusTool(plugin=plugin)
        result = await tool.execute(limit=5)
        assert result.data["returned_count"] == 5


class TestHeartbeatPluginSetAgent:
    def test_set_agent_reads_heartbeat_config(self):
        plugin = HeartbeatPlugin()
        mock_hb = MagicMock()
        mock_hb.enabled = False
        mock_hb.interval = 60
        mock_hb.timeout = 300
        mock_config = MagicMock()
        mock_config.heartbeat = mock_hb
        mock_agent = MagicMock(config=mock_config)
        plugin.set_agent(mock_agent)
        assert plugin._enabled is False
        assert plugin._push_interval == 60


class TestOnPluginHeartbeat:
    def test_on_plugin_heartbeat_appends_event(self):
        plugin = _make_hb()
        plugin.on_plugin_heartbeat(
            event="generated",
            data={
                "plugin_name": "plan",
                "plugin_id": "plan-abc123",
                "plan_id": "plan-001",
                "num_plans": 3,
            }
        )
        assert len(plugin._messages) == 1
        msg = plugin._messages[0]
        assert msg.event_type == "plugin_heartbeat"
        assert msg.event == "generated"
        assert msg.plugin_name == "plan"
        assert msg.plugin_id == "plan-abc123"
        assert msg.data["plan_id"] == "plan-001"
        assert msg.data["num_plans"] == 3

    def test_on_plugin_heartbeat_strips_plugin_info_from_data(self):
        plugin = _make_hb()
        plugin.on_plugin_heartbeat(
            event="scored",
            data={
                "plugin_name": "plan",
                "plugin_id": "plan-xyz",
                "plan_id": "p1",
                "scores": [85, 75],
            }
        )
        msg = plugin._messages[0]
        assert "plugin_name" not in msg.data
        assert "plugin_id" not in msg.data
        assert msg.data["plan_id"] == "p1"
        assert msg.data["scores"] == [85, 75]

    def test_on_plugin_heartbeat_ignores_when_disabled(self):
        plugin = _make_hb()
        plugin._enabled = False
        plugin.on_plugin_heartbeat(event="test", data={"plugin_name": "test"})
        assert len(plugin._messages) == 0

    def test_on_plugin_heartbeat_subtask_events(self):
        plugin = _make_hb()
        plugin.on_plugin_heartbeat(
            event="subtask_started",
            data={
                "plugin_name": "plan",
                "plugin_id": "plan-123",
                "plan_id": "p1",
                "subtask_id": "p1-1",
                "subtask_title": "Analyze code",
            }
        )
        msg = plugin._messages[0]
        assert msg.event == "subtask_started"
        assert msg.data["subtask_id"] == "p1-1"
        assert msg.data["subtask_title"] == "Analyze code"

    def test_on_plugin_heartbeat_execute_events(self):
        plugin = _make_hb()
        plugin.on_plugin_heartbeat(
            event="execute_started",
            data={
                "plugin_name": "plan",
                "plugin_id": "plan-123",
                "plan_id": "p1",
                "plan_name": "Conservative",
                "num_subtasks": 5,
            }
        )
        plugin.on_plugin_heartbeat(
            event="execute_completed",
            data={
                "plugin_name": "plan",
                "plugin_id": "plan-123",
                "plan_id": "p1",
                "success": True,
                "completed": 5,
                "failed": 0,
                "duration_s": 120.5,
            }
        )
        assert len(plugin._messages) == 2
        start_msg = plugin._messages[0]
        end_msg = plugin._messages[1]
        assert start_msg.event == "execute_started"
        assert start_msg.data["num_subtasks"] == 5
        assert end_msg.event == "execute_completed"
        assert end_msg.data["completed"] == 5
        assert end_msg.data["duration_s"] == 120.5
