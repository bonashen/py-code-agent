"""Test skill context tracking and plugin prompt injection in PlanPlugin.

These tests verify:
- Option A: Subagent inherits plugin system prompts from plugin_manager (_run_subtask)
- Option B: Skill tool results are tracked and propagated to subtasks (plan_task)
"""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

_repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(_repo_root))

from plugins.builtin.plan_plugin import Plan, PlanPlugin, PlanTaskTool, SubTask


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
# Option A: Plugin prompt injection in _run_subtask
# =============================================================================


class TestPluginPromptInjection:
    """Subagent must share the same plugin/skill ecosystem as the master agent."""

    @pytest.mark.asyncio
    async def test_run_subtask_includes_plugin_prompts(self):
        """_run_subtask should inject plugin system prompts into the subagent's prompt."""
        plugin, mock_agent = _make_plan_plugin()
        mock_agent.tools = {}
        mock_agent.config = None

        # Mock plugin_manager with get_system_prompt()
        mock_pm = MagicMock()
        mock_pm.get_system_prompt = MagicMock(
            return_value="## Skills\nUse docx-js for .docx files."
        )
        mock_agent.plugin_manager = mock_pm

        # Track what system prompt was sent to the LLM
        captured_prompts = []

        async def capture_complete(messages, **kwargs):
            # Extract system prompt from messages
            for msg in messages:
                if hasattr(msg, "content"):
                    captured_prompts.append(msg.content)
                elif isinstance(msg, dict) and msg.get("role") == "system":
                    captured_prompts.append(msg.get("content", ""))
            return MagicMock(
                get=lambda k, d=None: {"content": "done", "tool_calls": []}.get(k, d)
            )

        mock_agent.llm.complete = AsyncMock(side_effect=capture_complete)

        subtask = SubTask(
            id="st1",
            title="Create docx",
            description="Save answer as .docx",
        )
        ok, result = await plugin._run_subtask(subtask, mock_agent)

        assert ok is True
        assert len(captured_prompts) == 1
        prompt = captured_prompts[0]
        # Plugin prompt must be present
        assert "## Skills" in prompt
        assert "docx-js" in prompt
        # Subtask context must also be present
        assert "Create docx" in prompt
        assert "ReAct" in prompt

    @pytest.mark.asyncio
    async def test_run_subtask_includes_skill_context(self):
        """_run_subtask should inject skill_context into the subagent's prompt."""
        plugin, mock_agent = _make_plan_plugin()
        mock_agent.tools = {}
        mock_agent.config = None
        mock_agent.plugin_manager = MagicMock(
            get_system_prompt=MagicMock(return_value="")
        )

        captured_prompts = []

        async def capture_complete(messages, **kwargs):
            for msg in messages:
                if hasattr(msg, "content"):
                    captured_prompts.append(msg.content)
                elif isinstance(msg, dict) and msg.get("role") == "system":
                    captured_prompts.append(msg.get("content", ""))
            return MagicMock(
                get=lambda k, d=None: {"content": "done", "tool_calls": []}.get(k, d)
            )

        mock_agent.llm.complete = AsyncMock(side_effect=capture_complete)

        # Subtask with skill_context set (propagated from plan)
        subtask = SubTask(
            id="st1",
            title="Create docx",
            description="Save answer as .docx",
            skill_context="[Skill: docx]\nUse docx-js library. Read docx-js.md first.",
        )
        ok, result = await plugin._run_subtask(subtask, mock_agent)

        assert ok is True
        assert len(captured_prompts) == 1
        prompt = captured_prompts[0]
        # Skill workflow must be present
        assert "Required Skill Workflow" in prompt
        assert "docx-js" in prompt
        assert "[Skill: docx]" in prompt

    @pytest.mark.asyncio
    async def test_run_subtask_graceful_without_plugin_manager(self):
        """_run_subtask should not crash if plugin_manager is missing."""
        plugin, mock_agent = _make_plan_plugin()
        mock_agent.tools = {}
        mock_agent.config = None
        # No plugin_manager attribute
        del mock_agent.plugin_manager

        captured_prompts = []

        async def capture_complete(messages, **kwargs):
            for msg in messages:
                if hasattr(msg, "content"):
                    captured_prompts.append(msg.content)
            return MagicMock(
                get=lambda k, d=None: {"content": "done", "tool_calls": []}.get(k, d)
            )

        mock_agent.llm.complete = AsyncMock(side_effect=capture_complete)

        subtask = SubTask(id="st1", title="Test", description="Test subtask")
        ok, result = await plugin._run_subtask(subtask, mock_agent)

        # Must still succeed
        assert ok is True
        assert "Test" in captured_prompts[0]


# =============================================================================
# Option B: Skill context tracking in plan_task
# =============================================================================


class TestSkillContextExtraction:
    """PlanTaskTool must extract skill tool results from session messages."""

    @pytest.mark.asyncio
    async def test_plan_task_extracts_skill_tool_result(self):
        """plan_task should extract skill_<name> tool results from session messages."""
        plugin, mock_agent = _make_plan_plugin()

        # Mock LLM to return valid JSON plan
        mock_agent.llm.complete = AsyncMock(
            return_value=MagicMock(
                get=lambda k, d=None: {
                    "content": json.dumps([
                        {
                            "name": "Docx Approach",
                            "description": "Create docx using skill workflow",
                            "approach": "conservative",
                            "risk_level": "low",
                            "estimated_steps": 2,
                            "subtasks": [
                                {"title": "Draft content", "description": "Write answer content"},
                                {"title": "Save docx", "description": "Use docx-js to save"},
                            ],
                        }
                    ]),
                    "tool_calls": [],
                }.get(k, d)
            )
        )

        # Mock session with skill tool result
        mock_session = MagicMock()
        mock_session.messages = [
            {"role": "user", "content": "Save answer as .docx"},
            {
                "role": "tool",
                "name": "skill_docx",
                "content": json.dumps({
                    "success": True,
                    "data": {
                        "name": "docx",
                        "content": "# DOCX Skill\nUse docx-js library.",
                        "path": "/tmp/skills/docx",
                        "files": [],
                    },
                }),
            },
        ]
        mock_agent.session = mock_session

        tool = PlanTaskTool(plugin)
        result = await tool.execute(task="Save answer as .docx", num_plans=1)

        assert result.success is True
        plans_data = result.data["plans"]
        assert len(plans_data) == 1

        # Skill context must be attached to the plan
        plan_dict = plans_data[0]
        assert plan_dict["skill_context"] == "[Skill: docx]\n# DOCX Skill\nUse docx-js library."

    @pytest.mark.asyncio
    async def test_plan_task_no_skill_context_without_skill_call(self):
        """plan_task should work normally if no skill tool was called."""
        plugin, mock_agent = _make_plan_plugin()

        mock_agent.llm.complete = AsyncMock(
            return_value=MagicMock(
                get=lambda k, d=None: {
                    "content": json.dumps([
                        {
                            "name": "Simple",
                            "description": "Simple approach",
                            "approach": "conservative",
                            "risk_level": "low",
                            "estimated_steps": 1,
                            "subtasks": [
                                {"title": "Do thing", "description": "Just do it"},
                            ],
                        }
                    ]),
                    "tool_calls": [],
                }.get(k, d)
            )
        )

        # Session with no skill tool results
        mock_session = MagicMock()
        mock_session.messages = [
            {"role": "user", "content": "Just do X"},
            {"role": "assistant", "content": "I'll do X."},
        ]
        mock_agent.session = mock_session

        tool = PlanTaskTool(plugin)
        result = await tool.execute(task="Do X", num_plans=1)

        assert result.success is True
        plan_dict = result.data["plans"][0]
        assert plan_dict["skill_context"] == ""


class TestSubtaskSkillContext:
    """ExecutePlanTool must propagate skill_context from plan to subtasks."""

    def test_execute_injects_skill_context_into_pending_subtasks(self):
        """Subtasks should receive skill_context from their parent plan before execution."""
        plugin, mock_agent = _make_plan_plugin()

        # Create a plan with skill_context
        plan = Plan(
            id="p1",
            name="Test Plan",
            description="Test",
            skill_context="[Skill: docx]\nUse docx-js library.",
        )
        plan.subtasks = [
            SubTask(id="st1", title="Step 1", description="Draft content"),
            SubTask(id="st2", title="Step 2", description="Save docx"),
        ]
        plugin._plans["p1"] = plan

        # Verify subtasks start without skill_context
        assert plan.subtasks[0].skill_context == ""
        assert plan.subtasks[1].skill_context == ""

        # Simulate what ExecutePlanTool does: inject skill_context into pending subtasks
        ready = [st for st in plan.subtasks if st.status == "pending"]
        for st in ready:
            if plan.skill_context and not st.skill_context:
                st.skill_context = plan.skill_context

        # Now subtasks should have skill_context
        assert plan.subtasks[0].skill_context == "[Skill: docx]\nUse docx-js library."
        assert plan.subtasks[1].skill_context == "[Skill: docx]\nUse docx-js library."

    def test_subtask_does_not_overwrite_existing_skill_context(self):
        """Subtask's own skill_context should not be overwritten by plan's."""
        plugin, mock_agent = _make_plan_plugin()

        plan = Plan(
            id="p1",
            name="Test Plan",
            description="Test",
            skill_context="[Plan skill: general]",
        )
        # Subtask already has its own specific skill_context
        plan.subtasks = [
            SubTask(
                id="st1",
                title="Step 1",
                description="Use docx skill",
                skill_context="[Subtask skill: docx-specific]",
            ),
        ]
        plugin._plans["p1"] = plan

        # Simulate injection
        ready = [st for st in plan.subtasks if st.status == "pending"]
        for st in ready:
            if plan.skill_context and not st.skill_context:
                st.skill_context = plan.skill_context

        # Subtask's own context must NOT be overwritten
        assert plan.subtasks[0].skill_context == "[Subtask skill: docx-specific]"


# =============================================================================
# Data structure tests for new fields
# =============================================================================


class TestSkillContextDataStructures:
    """Verify skill_context field exists and serializes correctly."""

    def test_subtask_skill_context_defaults_to_empty(self):
        """SubTask.skill_context defaults to ''."""
        st = SubTask(id="1", title="t", description="d")
        assert st.skill_context == ""

    def test_plan_skill_context_defaults_to_empty(self):
        """Plan.skill_context defaults to ''."""
        p = Plan(id="p1", name="n", description="d")
        assert p.skill_context == ""

    def test_subtask_skill_context_in_to_dict(self):
        """SubTask.to_dict() must include skill_context."""
        st = SubTask(
            id="1", title="t", description="d", skill_context="docx workflow"
        )
        d = st.to_dict()
        assert d["skill_context"] == "docx workflow"

    def test_plan_skill_context_in_to_dict(self):
        """Plan.to_dict() must include skill_context."""
        p = Plan(
            id="p1", name="n", description="d", skill_context="docx workflow"
        )
        d = p.to_dict()
        assert d["skill_context"] == "docx workflow"
