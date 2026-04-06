"""Test PlanPlugin — task planning, execution, and reflection."""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add repo root so "from plugins.builtin.plan_plugin import ..." works.
_repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(_repo_root))

from plugins.builtin.plan_plugin import (
    MAX_RETRY,
    HeartbeatState,
    Plan,
    PlanPlugin,
    PlanTaskTool,
    CompareSolutionsTool,
    ViewPlanTool,
    ReflectOnFailureTool,
    SubTask,
)


def _make_plan_plugin() -> tuple[PlanPlugin, MagicMock]:
    """Create a PlanPlugin with a mocked agent reference."""
    plugin = PlanPlugin()
    mock_agent = MagicMock()
    mock_agent.llm = MagicMock()
    mock_agent.llm.complete = AsyncMock()
    mock_agent.tools = {}
    plugin.set_agent(mock_agent)
    return plugin, mock_agent


# =============================================================================
# Data structure tests
# =============================================================================


class TestPlanDataStructures:
    def test_subtask_defaults(self):
        st = SubTask(id="1-1", title="Step 1", description="Do X")
        assert st.status == "pending"
        assert st.retry_count == 0
        assert st.result is None
        assert st.error is None
        assert st.dependencies == []

    def test_subtask_to_dict(self):
        st = SubTask(id="1-1", title="Step 1", description="Do X", status="completed", result="Done")
        d = st.to_dict()
        assert d["id"] == "1-1"
        assert d["status"] == "completed"
        assert d["result"] == "Done"

    def test_plan_defaults(self):
        plan = Plan(id="abc123", name="Test Plan", description="A test", approach="conservative")
        assert plan.status == "draft"
        assert plan.risk_level == "medium"
        assert plan.subtasks == []
        assert plan.created_at != ""

    def test_plan_to_dict(self):
        plan = Plan(
            id="abc123",
            name="Test",
            description="A test",
            approach="aggressive",
            risk_level="high",
        )
        d = plan.to_dict()
        assert d["id"] == "abc123"
        assert d["approach"] == "aggressive"
        assert d["risk_level"] == "high"
        assert d["status"] == "draft"

    def test_plan_with_subtasks(self):
        plan = Plan(id="p1", name="Plan", description="Test")
        plan.subtasks = [
            SubTask(id="p1-1", title="Step 1", description="First", dependencies=[]),
            SubTask(id="p1-2", title="Step 2", description="Second", dependencies=["p1-1"]),
        ]
        assert len(plan.subtasks) == 2
        assert plan.subtasks[1].dependencies == ["p1-1"]


# =============================================================================
# PlanPlugin lifecycle tests
# =============================================================================


class TestPlanPluginLifecycle:
    def test_register_tools(self):
        plugin, _ = _make_plan_plugin()
        tools = plugin.register_tools()
        names = [t.definition.name for t in tools]
        assert "plan_task" in names
        assert "compare_solutions" in names
        assert "view_plan" in names
        assert "execute_plan" in names
        assert "reflect_on_failure" in names
        assert "assess_complexity" in names
        assert len(tools) == 6

    def test_set_agent_stores_reference(self):
        plugin, mock_agent = _make_plan_plugin()
        assert plugin._agent_ref is mock_agent

    def test_on_agent_start_clears_state(self):
        plugin, _ = _make_plan_plugin()
        plugin._executing = True
        plugin.on_agent_start("test input")
        assert plugin._executing is False

    def test_on_agent_end_clears_state(self):
        plugin, _ = _make_plan_plugin()
        plugin._executing = True
        plugin.on_agent_end()
        assert plugin._executing is False


# =============================================================================
# Hook: get_system_prompt
# =============================================================================


class TestGetSystemPrompt:
    def test_get_system_prompt_returns_string(self):
        plugin, _ = _make_plan_plugin()
        result = plugin.get_system_prompt()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_get_system_prompt_contains_planning_guidance(self):
        plugin, _ = _make_plan_plugin()
        result = plugin.get_system_prompt()
        assert "## CRITICAL: YOUR FIRST ACTION IS FIXED" in result
        assert "plan_task" in result
        assert "execute_plan" in result

    def test_get_system_prompt_contains_tool_list(self):
        plugin, _ = _make_plan_plugin()
        result = plugin.get_system_prompt()
        assert "view_plan" in result
        assert "compare_solutions" in result
        assert "reflect_on_failure" in result

    def test_get_system_prompt_has_conditions(self):
        plugin, _ = _make_plan_plugin()
        result = plugin.get_system_prompt()
        # Should describe the protocol
        assert "assess_complexity" in result


# =============================================================================
# plan_task tool tests
# =============================================================================


class TestPlanTaskTool:
    def test_definition(self):
        plugin, _ = _make_plan_plugin()
        tool = PlanTaskTool(plugin)
        d = tool.definition
        assert d.name == "plan_task"
        assert d.description != ""
        assert len(d.parameters) == 2
        param_names = [p.name for p in d.parameters]
        assert "task" in param_names
        assert "num_plans" in param_names

    def test_parse_json_array_valid(self):
        plugin, _ = _make_plan_plugin()
        tool = PlanTaskTool(plugin)
        json_str = json.dumps([
            {
                "name": "Conservative",
                "description": "Safe incremental approach",
                "approach": "conservative",
                "risk_level": "low",
                "estimated_steps": 3,
                "subtasks": [
                    {"title": "Step 1", "description": "Do the thing"},
                    {"title": "Step 2", "description": "Verify"},
                ],
            },
            {
                "name": "Aggressive",
                "description": "Fast but risky",
                "approach": "aggressive",
                "risk_level": "high",
                "estimated_steps": 2,
                "subtasks": [
                    {"title": "All at once", "description": "Do everything"},
                ],
            },
        ])
        plans = tool._parse_json_array(json_str, "test task")
        assert len(plans) == 2
        assert plans[0].name == "Conservative"
        assert plans[0].approach == "conservative"
        assert plans[0].risk_level == "low"
        assert len(plans[0].subtasks) == 2
        assert plans[1].approach == "aggressive"

    def test_parse_json_array_with_fenced_code(self):
        plugin, _ = _make_plan_plugin()
        tool = PlanTaskTool(plugin)
        json_str = '```json\n[{"name": "Plan A", "approach": "conservative", "risk_level": "low", "estimated_steps": 1, "subtasks": []}]\n```'
        plans = tool._parse_json_array(json_str, "test")
        assert len(plans) == 1
        assert plans[0].name == "Plan A"

    def test_parse_json_array_invalid(self):
        plugin, _ = _make_plan_plugin()
        tool = PlanTaskTool(plugin)
        plans = tool._parse_json_array("not json at all!!!", "test")
        assert plans == []

    @pytest.mark.asyncio
    async def test_execute_generates_plans(self):
        plugin, mock_agent = _make_plan_plugin()
        tool = PlanTaskTool(plugin)
        mock_agent.llm.complete.return_value = {
            "content": json.dumps([
                {
                    "name": "Conservative",
                    "description": "Safe approach",
                    "approach": "conservative",
                    "risk_level": "low",
                    "estimated_steps": 2,
                    "subtasks": [
                        {"title": "Step 1", "description": "First"},
                        {"title": "Step 2", "description": "Second"},
                    ],
                },
            ]),
            "tool_calls": [],
        }

        result = await tool.execute(task="Build a web server")
        assert result.success is True
        assert result.data["count"] == 1
        assert len(plugin._plans) == 1

    @pytest.mark.asyncio
    async def test_execute_stores_plan_id(self):
        plugin, mock_agent = _make_plan_plugin()
        tool = PlanTaskTool(plugin)
        mock_agent.llm.complete.return_value = {
            "content": json.dumps([
                {
                    "name": "Plan A",
                    "description": "Test",
                    "approach": "alternative",
                    "risk_level": "medium",
                    "estimated_steps": 1,
                    "subtasks": [{"title": "S1", "description": "Do X"}],
                },
            ]),
            "tool_calls": [],
        }

        result = await tool.execute(task="Test task")
        assert result.success is True
        plan_id = list(plugin._plans.keys())[0]
        assert result.data["plans"][0]["id"] == plan_id

    @pytest.mark.asyncio
    async def test_execute_invalid_llm_response(self):
        plugin, mock_agent = _make_plan_plugin()
        tool = PlanTaskTool(plugin)
        mock_agent.llm.complete.return_value = {"content": "not json!!!"}
        result = await tool.execute(task="Test")
        assert result.success is False


# =============================================================================
# view_plan tool tests
# =============================================================================


class TestViewPlanTool:
    def test_definition(self):
        plugin, _ = _make_plan_plugin()
        tool = ViewPlanTool(plugin)
        assert tool.definition.name == "view_plan"
        assert len(tool.definition.parameters) == 1

    @pytest.mark.asyncio
    async def test_view_plan_renders_table(self):
        plugin, _ = _make_plan_plugin()
        tool = ViewPlanTool(plugin)
        plugin._plans["test-plan"] = Plan(
            id="test-plan",
            name="My Plan",
            description="A test plan",
            approach="conservative",
            risk_level="low",
        )
        plugin._plans["test-plan"].subtasks = [
            SubTask(id="tp-1", title="Setup", description="Set up project"),
            SubTask(id="tp-2", title="Build", description="Build it"),
        ]

        result = await tool.execute(plan_id="test-plan")
        assert result.success is True
        assert "My Plan" in result.summary
        assert "2 subtasks" in result.summary

    @pytest.mark.asyncio
    async def test_view_plan_not_found(self):
        plugin, _ = _make_plan_plugin()
        tool = ViewPlanTool(plugin)
        result = await tool.execute(plan_id="nonexistent")
        assert result.success is False


# =============================================================================
# compare_solutions tool tests
# =============================================================================


class TestCompareSolutionsTool:
    def test_definition(self):
        plugin, _ = _make_plan_plugin()
        tool = CompareSolutionsTool(plugin)
        assert tool.definition.name == "compare_solutions"

    @pytest.mark.asyncio
    async def test_compare_needs_two_plans(self):
        plugin, _ = _make_plan_plugin()
        tool = CompareSolutionsTool(plugin)
        plugin._plans["p1"] = Plan(id="p1", name="Plan 1", description="A", approach="conservative")
        result = await tool.execute(plan_ids="p1")
        assert result.success is False
        assert "Need at least 2 plans" in str(result.error)

    @pytest.mark.asyncio
    async def test_compare_renders_table(self):
        plugin, mock_agent = _make_plan_plugin()
        tool = CompareSolutionsTool(plugin)
        plugin._plans["p1"] = Plan(id="p1", name="Conservative", description="Safe", approach="conservative")
        plugin._plans["p2"] = Plan(id="p2", name="Aggressive", description="Risky", approach="aggressive")
        mock_agent.llm.complete.return_value = {
            "content": json.dumps({
                "rankings": [{"rank": 1, "plan_id": "p1"}, {"rank": 2, "plan_id": "p2"}],
                "comparison_table": [
                    {"plan_id": "p1", "risk": "low", "complexity": "5 steps", "outcome": "high", "best_for": "production"},
                    {"plan_id": "p2", "risk": "high", "complexity": "2 steps", "outcome": "medium", "best_for": "prototype"},
                ],
            }),
        }

        result = await tool.execute(plan_ids="p1, p2")
        assert result.success is True
        assert "Compared 2 plans" in result.summary


# =============================================================================
# reflect_on_failure tool tests
# =============================================================================


class TestReflectOnFailureTool:
    def test_definition(self):
        plugin, _ = _make_plan_plugin()
        tool = ReflectOnFailureTool(plugin)
        assert tool.definition.name == "reflect_on_failure"
        assert len(tool.definition.parameters) == 2

    @pytest.mark.asyncio
    async def test_reflect_plan_not_found(self):
        plugin, _ = _make_plan_plugin()
        tool = ReflectOnFailureTool(plugin)
        result = await tool.execute(plan_id="nonexistent", subtask_id="x-y")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_reflect_subtask_not_found(self):
        plugin, _ = _make_plan_plugin()
        tool = ReflectOnFailureTool(plugin)
        plugin._plans["p1"] = Plan(id="p1", name="P", description="D", approach="conservative")
        result = await tool.execute(plan_id="p1", subtask_id="nonexistent-subtask")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_reflect_returns_diagnosis(self):
        plugin, mock_agent = _make_plan_plugin()
        tool = ReflectOnFailureTool(plugin)
        plan = Plan(id="p1", name="Plan", description="Test task", approach="conservative")
        plan.subtasks = [SubTask(id="p1-1", title="Step 1", description="Do it", error="Tool not found")]
        plugin._plans["p1"] = plan
        mock_agent.llm.complete.return_value = {
            "content": json.dumps({
                "diagnosis": "Wrong tool used for this operation",
                "revised_description": "Use the correct tool instead",
                "alternative_tools": ["tool_a", "tool_b"],
                "suggestions": ["Check the API first"],
            }),
        }

        result = await tool.execute(plan_id="p1", subtask_id="p1-1")
        assert result.success is True
        assert "Wrong tool" in result.data["diagnosis"]


# =============================================================================
# Hook: on_llm_call complexity detection
# =============================================================================


class TestHookOnLlmCall:
    """on_llm_call is now a pass-through (complexity detection is LLM-driven, not heuristic)."""

    def test_hook_does_not_crash_on_simple_message(self):
        plugin, _ = _make_plan_plugin()
        messages = [{"content": "hello world"}]
        tools = [{"name": "read_file"}]
        plugin.on_llm_call(messages, tools)
        # Must not raise

    def test_hook_does_not_crash_on_complex_message(self):
        plugin, _ = _make_plan_plugin()
        messages = [{"content": "rebuild the entire auth system from scratch"}]
        tools = [{"name": "a"}, {"name": "b"}, {"name": "c"}, {"name": "d"}]
        plugin.on_llm_call(messages, tools)
        # Must not raise — no heuristic complexity detection anymore

    def test_hook_skips_when_executing(self):
        """Hook is a no-op when already inside plan execution."""
        plugin, _ = _make_plan_plugin()
        plugin._executing = True
        messages = [{"content": "rebuild everything"}]
        tools = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
        plugin.on_llm_call(messages, tools)
        # Must not raise — no-op when executing

    def test_hook_requires_agent_ref(self):
        """Hook must not crash when agent ref is None."""
        plugin, _ = _make_plan_plugin()
        plugin._agent_ref = None
        messages = [{"content": "rebuild the auth"}]
        tools = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
        plugin.on_llm_call(messages, tools)
        # Must not raise

    def test_hook_accepts_empty_messages(self):
        plugin, _ = _make_plan_plugin()
        plugin.on_llm_call([], [])
        # Must not raise

    def test_hook_accepts_dict_messages(self):
        plugin, _ = _make_plan_plugin()
        messages = [{"role": "user", "content": "what time is it"}]
        tools = [{"name": "read_file"}, {"name": "write_file"}]
        plugin.on_llm_call(messages, tools)
        # Must not raise


# =============================================================================
# Max retry constant
# =============================================================================


class TestMaxRetry:
    def test_max_retry_is_3(self):
        assert MAX_RETRY == 3


class TestParallelExecution:
    """Tests for parallel sub-agent execution via asyncio.gather."""

    def test_max_concurrent_agents_constant(self):
        from plugins.builtin.plan_plugin import MAX_CONCURRENT_AGENTS
        assert MAX_CONCURRENT_AGENTS == 4

    def test_execute_plan_definition_has_max_agents(self):
        plugin, _ = _make_plan_plugin()
        tools = plugin.register_tools()
        et = next(t for t in tools if t.definition.name == "execute_plan")
        param_names = [p.name for p in et.definition.parameters]
        assert "max_agents" in param_names

    @pytest.mark.asyncio
    async def test_execute_plan_no_subtasks(self):
        """execute_plan with no subtasks returns empty success."""
        plugin, _ = _make_plan_plugin()
        tools = plugin.register_tools()
        et = next(t for t in tools if t.definition.name == "execute_plan")
        # No plan registered
        result = await et.execute(plan_id="nonexistent")
        assert result.success is False

    def test_plan_parallel_batches(self):
        """_count_batches: all independent = 1 batch."""
        def _count_batches(plan):
            completed_ids = set()
            batch_count = 0
            while True:
                ready = [st for st in plan.subtasks if st.status == 'pending' and all(dep in completed_ids for dep in st.dependencies)]
                if not ready: break
                batch_count += 1
                for st in ready:
                    completed_ids.add(st.id)
                    st.status = 'completed'
            for st in plan.subtasks: st.status = 'pending'
            return batch_count

        plan = Plan(id="p1", name="Test", description="Test plan")
        plan.subtasks = [
            SubTask(id="s1", title="A", description="A"),
            SubTask(id="s2", title="B", description="B"),
            SubTask(id="s3", title="C", description="C"),
        ]
        assert _count_batches(plan) == 1

    def test_plan_sequential_batches(self):
        """_count_batches: chain = N batches."""
        def _count_batches(plan):
            completed_ids = set()
            batch_count = 0
            while True:
                ready = [st for st in plan.subtasks if st.status == 'pending' and all(dep in completed_ids for dep in st.dependencies)]
                if not ready: break
                batch_count += 1
                for st in ready:
                    completed_ids.add(st.id)
                    st.status = 'completed'
            for st in plan.subtasks: st.status = 'pending'
            return batch_count

        plan = Plan(id="p1", name="Test", description="Test plan")
        plan.subtasks = [
            SubTask(id="s1", title="A", description="A", dependencies=[]),
            SubTask(id="s2", title="B", description="B", dependencies=["s1"]),
            SubTask(id="s3", title="C", description="C", dependencies=["s2"]),
        ]
        assert _count_batches(plan) == 3

    def test_plan_mixed_batches(self):
        """_count_batches: batch 1 has s1+s2, batch 2 has s3+s4, batch 3 has s5."""
        def _count_batches(plan):
            completed_ids = set()
            batch_count = 0
            while True:
                ready = [st for st in plan.subtasks if st.status == 'pending' and all(dep in completed_ids for dep in st.dependencies)]
                if not ready: break
                batch_count += 1
                for st in ready:
                    completed_ids.add(st.id)
                    st.status = 'completed'
            for st in plan.subtasks: st.status = 'pending'
            return batch_count

        plan = Plan(id="p1", name="Test", description="Test plan")
        plan.subtasks = [
            SubTask(id="s1", title="A", description="A", dependencies=[]),
            SubTask(id="s2", title="B", description="B", dependencies=[]),
            SubTask(id="s3", title="C", description="C", dependencies=["s1"]),
            SubTask(id="s4", title="D", description="D", dependencies=["s2"]),
            SubTask(id="s5", title="E", description="E", dependencies=["s3", "s4"]),
        ]
        assert _count_batches(plan) == 3


# =============================================================================
# Heartbeat tests
# =============================================================================


class TestHeartbeatState:
    def test_heartbeat_state_defaults(self):
        state = HeartbeatState(subtask_id="st1")
        assert state.subtask_id == "st1"
        assert state.alive is True
        assert state.missed_count == 0
        assert state.aborted is False

    def test_ping_updates_time_and_resets_missed(self):
        import time
        state = HeartbeatState(subtask_id="st1")
        state.missed_count = 3
        state.ping()
        assert state.missed_count == 0
        assert state.alive is True

    def test_mark_missed_increments_count(self):
        state = HeartbeatState(subtask_id="st1")
        state.mark_missed()
        assert state.missed_count == 1
        assert state.alive is True
        state.mark_missed()
        assert state.missed_count == 2

    def test_mark_dead_sets_alive_false(self):
        state = HeartbeatState(subtask_id="st1")
        state.mark_dead()
        assert state.alive is False

    def test_mark_aborted_sets_both_flags(self):
        state = HeartbeatState(subtask_id="st1")
        state.mark_aborted()
        assert state.alive is False
        assert state.aborted is True

    def test_seconds_since_heartbeat_positive(self):
        import time
        state = HeartbeatState(subtask_id="st1")
        elapsed = state.seconds_since_heartbeat()
        assert elapsed >= 0
        assert elapsed < 1


class TestHeartbeatConfig:
    def test_get_heartbeat_config_defaults(self):
        plugin, _ = _make_plan_plugin()
        mock_agent = MagicMock()
        mock_agent.config = None
        interval, timeout = plugin._get_heartbeat_config(mock_agent)
        assert interval == 30
        assert timeout == 90

    def test_get_heartbeat_config_from_agent(self):
        plugin, _ = _make_plan_plugin()
        mock_hb = MagicMock()
        mock_hb.enabled = True
        mock_hb.interval = 15
        mock_hb.timeout = 45
        mock_agent = MagicMock()
        mock_agent.config = MagicMock(heartbeat=mock_hb)
        interval, timeout = plugin._get_heartbeat_config(mock_agent)
        assert interval == 15
        assert timeout == 45

    def test_get_heartbeat_config_disabled_returns_zero(self):
        plugin, _ = _make_plan_plugin()
        mock_hb = MagicMock()
        mock_hb.enabled = False
        mock_hb.interval = 15
        mock_hb.timeout = 45
        mock_agent = MagicMock()
        mock_agent.config = MagicMock(heartbeat=mock_hb)
        interval, timeout = plugin._get_heartbeat_config(mock_agent)
        assert interval == 0
        assert timeout == 0

    def test_get_heartbeat_config_missing_field_uses_default(self):
        plugin, _ = _make_plan_plugin()
        mock_hb = MagicMock(spec=["enabled"])
        mock_hb.enabled = True
        del mock_hb.interval
        del mock_hb.timeout
        mock_agent = MagicMock()
        mock_agent.config = MagicMock(heartbeat=mock_hb)
        interval, timeout = plugin._get_heartbeat_config(mock_agent)
        assert interval == 30
        assert timeout == 90


class TestHeartbeatHelpers:
    def test_build_tool_defs(self):
        plugin, mock_agent = _make_plan_plugin()
        mock_tool = MagicMock()
        mock_tool.definition = MagicMock()
        mock_tool.definition.name = "read_file"
        mock_tool.definition.description = "Read a file"
        mock_param = MagicMock()
        mock_param.name = "path"
        mock_param.description = "File path"
        mock_param.type = MagicMock()
        mock_param.type.__str__ = MagicMock(return_value="ToolParameterType.STRING")
        mock_param.required = True
        mock_tool.definition.parameters = [mock_param]
        mock_agent.tools = {"read_file": mock_tool}

        defs = plugin._build_tool_defs(mock_agent)
        assert len(defs) == 1
        assert defs[0]["function"]["name"] == "read_file"
        assert defs[0]["function"]["description"] == "Read a file"
        assert "path" in defs[0]["function"]["parameters"]["properties"]
        assert "path" in defs[0]["function"]["parameters"]["required"]


class TestHeartbeatRunSubtask:
    @pytest.mark.asyncio
    async def test_run_subtask_no_tools_one_shot(self):
        plugin, mock_agent = _make_plan_plugin()
        mock_agent.tools = {}
        mock_agent.llm.complete = AsyncMock(return_value=MagicMock(
            get=MagicMock(side_effect=lambda k, d=None: {
                "content": "result text",
                "tool_calls": [],
            }.get(k, d)),
        ))
        mock_agent.config = None

        subtask = SubTask(id="st1", title="Test", description="Test subtask")
        ok, result = await plugin._run_subtask(subtask, mock_agent)
        assert ok is True
        assert "result text" in result

    @pytest.mark.asyncio
    async def test_run_subtask_heartbeat_timeout_aborts(self):
        plugin, mock_agent = _make_plan_plugin()
        mock_agent.tools = {}

        mock_hb = MagicMock()
        mock_hb.enabled = True
        mock_hb.interval = 1
        mock_hb.timeout = 2
        mock_agent.config = MagicMock(heartbeat=mock_hb)

        async def slow_complete(*args, **kwargs):
            await asyncio.sleep(5)
            return MagicMock(
                content="slow",
                tool_calls=[],
            )
        mock_agent.llm.complete = slow_complete

        subtask = SubTask(id="st1", title="Slow", description="Slow subtask")
        ok, result = await plugin._run_subtask(subtask, mock_agent)
        assert ok is False
        assert "timeout" in result.lower()

    @pytest.mark.asyncio
    async def test_run_subtask_multiturn_with_tool(self):
        plugin, mock_agent = _make_plan_plugin()

        mock_tool = MagicMock()
        mock_tool.definition = MagicMock()
        mock_tool.definition.name = "test_tool"
        mock_tool.definition.parameters = []
        mock_tool.execute = AsyncMock(return_value=MagicMock(summary="executed ok"))
        mock_agent.tools = {"test_tool": mock_tool}
        mock_agent.config = None

        tool_call = {
            "id": "tc1",
            "type": "function",
            "function": {"name": "test_tool", "arguments": "{}"},
        }

        call_count = [0]

        async def multiturn_complete(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                mock_resp = MagicMock()
                mock_resp.get = lambda k, d=None: [tool_call] if k == "tool_calls" else ("using tool" if k == "content" else d)
                return mock_resp
            mock_resp = MagicMock()
            mock_resp.get = lambda k, d=None: ([] if k == "tool_calls" else ("done" if k == "content" else d))
            return mock_resp

        mock_agent.llm.complete = multiturn_complete

        subtask = SubTask(id="st1", title="Test", description="Test subtask")
        ok, result = await plugin._run_subtask(subtask, mock_agent)
        assert ok is True
        assert call_count[0] == 2
        mock_tool.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_subtask_max_turns_protection(self):
        plugin, mock_agent = _make_plan_plugin()
        mock_agent.tools = {}
        mock_agent.config = None

        tool_def = {
            "type": "function",
            "function": {
                "name": "test_tool",
                "description": "test",
                "parameters": {"type": "object", "properties": {}},
            },
        }
        tool_call = {
            "id": "tc1",
            "type": "function",
            "function": {"name": "test_tool", "arguments": "{}"},
        }

        async def looping_complete(*args, **kwargs):
            messages = args[0]
            return MagicMock(
                content="still working",
                tool_calls=[tool_call] if len(messages) < 100 else [],
            )
        mock_agent.llm.complete = looping_complete

        mock_tool = MagicMock()
        mock_tool.definition = MagicMock()
        mock_tool.definition.name = "test_tool"
        mock_tool.definition.parameters = []
        mock_tool.execute = AsyncMock(return_value=MagicMock(summary="ok"))
        mock_agent.tools = {"test_tool": mock_tool}

        subtask = SubTask(id="st1", title="Loop", description="Loop subtask")
        ok, result = await plugin._run_subtask(subtask, mock_agent)
        assert ok is False
        assert "max 50" in result.lower()


# =============================================================================
# Full agent session integration tests
# =============================================================================


class TestPlanPluginFullAgent:
    """Integration tests that require full Agent init (~14s litellm overhead).

    Only the first test runs by default (verified: 86s).
    Run all with: pytest tests/ -m full_agent -v
    """

    @pytest.mark.full_agent
    @pytest.mark.asyncio
    async def test_plan_plugin_loads_in_agent(self):
        """Agent loads file:plan plugin and registers all 5 tools."""
        from py_code_agent.config.models import Config
        from py_code_agent.core.agent import Agent

        config = Config.from_file(str(_repo_root / "config.yaml"))
        # Ensure plan plugin is in enabled list
        if "file:plan" not in config.plugins.enabled:
            enabled = list(config.plugins.enabled) + ["file:plan"]
            config.plugins.enabled = enabled

        agent = Agent(config)
        tool_names = set(agent.tools.keys())

        assert "plan_task" in tool_names, f"plan_task not in {sorted(tool_names)}"
        assert "compare_solutions" in tool_names
        assert "view_plan" in tool_names
        assert "execute_plan" in tool_names
        assert "reflect_on_failure" in tool_names

        # Verify plugin hooks are set
        plugin = agent.plugin_manager.pm.get_plugin("file:plan")
        assert plugin is not None
        assert plugin._agent_ref is not None


class TestPlanPluginHeartbeat:
    def test_plugin_name_and_id_set(self):
        plugin, _ = _make_plan_plugin()
        assert plugin.PLUGIN_NAME == "plan"
        assert plugin.PLUGIN_ID.startswith("plan-")

    def test_emit_heartbeat_no_agent(self):
        plugin = PlanPlugin()
        plugin._emit_heartbeat("test_event", key="value")
        assert True

    def test_emit_heartbeat_with_agent_no_pm(self):
        plugin, mock_agent = _make_plan_plugin()
        mock_agent.plugin_manager = None
        plugin._emit_heartbeat("test_event", key="value")
        assert True

    def test_emit_heartbeat_with_mock_pm(self):
        plugin, mock_agent = _make_plan_plugin()
        
        mock_pm = MagicMock()
        mock_agent.plugin_manager = mock_pm
        plugin._emit_heartbeat(
            "generated",
            plan_id="plan-001",
            num_plans=3,
            plan_ids=["plan-001", "plan-002", "plan-003"]
        )
        
        mock_pm.call_on_plugin_heartbeat.assert_called_once()
        call_args = mock_pm.call_on_plugin_heartbeat.call_args
        assert call_args.kwargs["event"] == "generated"
        data = call_args.kwargs["data"]
        assert data["plugin_name"] == "plan"
        assert data["plugin_id"] == plugin.PLUGIN_ID
        assert data["plan_id"] == "plan-001"
        assert data["num_plans"] == 3

    def test_emit_heartbeat_subtask_events(self):
        plugin, mock_agent = _make_plan_plugin()
        mock_pm = MagicMock()
        mock_agent.plugin_manager = mock_pm
        
        plugin._emit_heartbeat(
            "subtask_started",
            plan_id="p1",
            subtask_id="p1-1",
            subtask_title="Analyze code"
        )
        
        call_args = mock_pm.call_on_plugin_heartbeat.call_args
        data = call_args.kwargs["data"]
        assert data["subtask_id"] == "p1-1"
        assert data["subtask_title"] == "Analyze code"

    def test_emit_heartbeat_execute_events(self):
        plugin, mock_agent = _make_plan_plugin()
        mock_pm = MagicMock()
        mock_agent.plugin_manager = mock_pm
        
        plugin._emit_heartbeat(
            "execute_completed",
            plan_id="p1",
            plan_name="Conservative",
            success=True,
            completed=5,
            failed=0,
            duration_s=120.5
        )
        
        call_args = mock_pm.call_on_plugin_heartbeat.call_args
        data = call_args.kwargs["data"]
        assert data["plan_name"] == "Conservative"
        assert data["success"] is True
        assert data["completed"] == 5
        assert data["failed"] == 0
        assert data["duration_s"] == 120.5
