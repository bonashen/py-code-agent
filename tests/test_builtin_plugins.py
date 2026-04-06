"""Test built-in plugins: log, soul, agent_identity, skills.

These are the plugins enabled in config.yaml for the project.
Tests avoid importing Config/Agent to prevent the slow litellm initialization,
using PluginConfig directly instead.
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add repo root so "from plugins.builtin.xxx import ..." works.
_repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(_repo_root))

# Avoid importing Config/Agent — they pull in litellm (13s import overhead).
from py_code_agent.config.models import PluginConfig
from py_code_agent.plugins.manager import PluginManager

_plugins_builtin = _repo_root / "plugins" / "builtin"


def _make_pm(*plugin_names: str) -> PluginManager:
    """Create a PluginManager with given plugins enabled."""
    cfg = PluginConfig(enabled=list(plugin_names), disabled=[])
    mgr = PluginManager(plugin_config=cfg)
    mgr.load_plugins([_plugins_builtin])
    return mgr


# =============================================================================
# LogPlugin tests
# =============================================================================

class TestLogPluginLoading:
    def test_loads_via_manager(self):
        mgr = _make_pm("file:log")
        assert "file:log" in mgr.loaded_plugins

    def test_registers_get_tool_log_tool(self):
        mgr = _make_pm("file:log")
        tools = mgr.register_tools()
        tool_names = [t.definition.name for t in tools]
        assert "get_tool_log" in tool_names

    def test_hook_methods_exist(self):
        mgr = _make_pm("file:log")
        log_plugin = mgr.pm.get_plugin("file:log")
        assert log_plugin is not None
        assert hasattr(log_plugin, "on_agent_start")
        assert hasattr(log_plugin, "on_agent_end")
        assert hasattr(log_plugin, "before_tool_execute")
        assert hasattr(log_plugin, "after_tool_execute")


class TestLogPluginHooks:
    def test_on_agent_start_records_event(self):
        mgr = _make_pm("file:log")
        log_plugin = mgr.pm.get_plugin("file:log")
        log_plugin.log.clear()
        mgr.call_on_agent_start("Hello world")
        assert len(log_plugin.log) == 1
        assert log_plugin.log[0]["event"] == "agent_start"
        assert log_plugin.log[0]["input"] == "Hello world"

    def test_before_tool_execute_records_event(self):
        mgr = _make_pm("file:log")
        log_plugin = mgr.pm.get_plugin("file:log")
        log_plugin.log.clear()
        mgr.call_before_tool_execute("read_file", {"path": "/tmp/test"})
        assert len(log_plugin.log) == 1
        assert log_plugin.log[0]["event"] == "tool_before"
        assert log_plugin.log[0]["tool"] == "read_file"

    def test_after_tool_execute_records_success(self):
        mgr = _make_pm("file:log")
        log_plugin = mgr.pm.get_plugin("file:log")
        log_plugin.log.clear()
        mgr.call_after_tool_execute(
            "read_file",
            {"path": "/tmp/test"},
            {"success": True, "data": "hello"},
        )
        assert len(log_plugin.log) == 1
        assert log_plugin.log[0]["event"] == "tool_after"
        assert log_plugin.log[0]["success"] is True

    def test_after_tool_execute_records_failure(self):
        mgr = _make_pm("file:log")
        log_plugin = mgr.pm.get_plugin("file:log")
        log_plugin.log.clear()
        mgr.call_after_tool_execute(
            "write_file",
            {"path": "/tmp/test"},
            {"success": False, "error": "Permission denied"},
        )
        assert len(log_plugin.log) == 1
        assert log_plugin.log[0]["event"] == "tool_after"
        assert log_plugin.log[0]["success"] is False


class TestLogPluginToolExecution:
    @pytest.mark.asyncio
    async def test_get_tool_log_returns_entries(self):
        mgr = _make_pm("file:log")
        log_plugin = mgr.pm.get_plugin("file:log")
        log_plugin.log.clear()
        mgr.call_on_agent_start("test input")
        mgr.call_before_tool_execute("read_file", {})
        mgr.call_after_tool_execute("read_file", {}, {"success": True})

        tools = mgr.register_tools()
        get_log_tool = next(t for t in tools if t.definition.name == "get_tool_log")
        result = await get_log_tool.execute()

        assert result.success is True
        assert result.data["count"] == 3


class TestLogPluginHeartbeat:
    def test_on_plugin_heartbeat_records_event(self):
        mgr = _make_pm("file:log")
        log_plugin = mgr.pm.get_plugin("file:log")
        log_plugin.log.clear()
        
        mgr.call_on_plugin_heartbeat(
            event="generated",
            data={
                "plugin_name": "plan",
                "plugin_id": "plan-abc123",
                "plan_id": "plan-001",
                "num_plans": 3,
            }
        )
        
        assert len(log_plugin.log) == 1
        entry = log_plugin.log[0]
        assert entry["event"] == "plugin_heartbeat"
        assert entry["plugin_event"] == "generated"
        assert entry["plugin_name"] == "plan"
        assert entry["plugin_id"] == "plan-abc123"
        assert entry["data"]["plan_id"] == "plan-001"
        assert entry["data"]["num_plans"] == 3

    def test_on_plugin_heartbeat_multiple_events(self):
        mgr = _make_pm("file:log")
        log_plugin = mgr.pm.get_plugin("file:log")
        log_plugin.log.clear()
        
        mgr.call_on_plugin_heartbeat(
            event="execute_started",
            data={"plugin_name": "plan", "plugin_id": "p1", "plan_id": "p1", "num_subtasks": 5}
        )
        mgr.call_on_plugin_heartbeat(
            event="subtask_started",
            data={"plugin_name": "plan", "plugin_id": "p1", "plan_id": "p1", "subtask_id": "p1-1"}
        )
        mgr.call_on_plugin_heartbeat(
            event="subtask_completed",
            data={"plugin_name": "plan", "plugin_id": "p1", "plan_id": "p1", "subtask_id": "p1-1", "success": True}
        )
        mgr.call_on_plugin_heartbeat(
            event="execute_completed",
            data={"plugin_name": "plan", "plugin_id": "p1", "plan_id": "p1", "success": True, "completed": 5}
        )
        
        assert len(log_plugin.log) == 4
        assert log_plugin.log[0]["plugin_event"] == "execute_started"
        assert log_plugin.log[1]["plugin_event"] == "subtask_started"
        assert log_plugin.log[2]["plugin_event"] == "subtask_completed"
        assert log_plugin.log[3]["plugin_event"] == "execute_completed"

    @pytest.mark.asyncio
    async def test_get_tool_log_includes_plugin_heartbeat(self):
        mgr = _make_pm("file:log")
        log_plugin = mgr.pm.get_plugin("file:log")
        log_plugin.log.clear()
        
        mgr.call_on_plugin_heartbeat(
            event="scored",
            data={"plugin_name": "plan", "plugin_id": "p1", "plan_id": "p1", "scores": [85, 75]}
        )
        
        tools = mgr.register_tools()
        get_log_tool = next(t for t in tools if t.definition.name == "get_tool_log")
        result = await get_log_tool.execute()
        
        assert result.success is True
        assert result.data["count"] == 1
        assert result.data["log"][0]["plugin_event"] == "scored"


class TestLogPluginWithPlanPluginHeartbeat:
    """Integration test: LogPlugin listening to PlanPlugin heartbeat events."""

    def test_plan_plugin_sends_heartbeat_log_plugin_receives(self):
        mgr = _make_pm("file:log", "file:plan")
        log_plugin = mgr.pm.get_plugin("file:log")
        plan_plugin = mgr.pm.get_plugin("file:plan")
        log_plugin.log.clear()
        
        mock_agent = MagicMock()
        mock_agent.plugin_manager = mgr
        plan_plugin.set_agent(mock_agent)
        
        plan_plugin._emit_heartbeat(
            "generated",
            plan_id="plan-001",
            num_plans=3,
            plan_ids=["plan-001", "plan-002", "plan-003"]
        )
        
        assert len(log_plugin.log) == 1
        entry = log_plugin.log[0]
        assert entry["event"] == "plugin_heartbeat"
        assert entry["plugin_event"] == "generated"
        assert entry["plugin_name"] == "plan"
        assert entry["data"]["plan_id"] == "plan-001"
        assert entry["data"]["num_plans"] == 3

    def test_plan_plugin_execute_lifecycle_logged(self):
        mgr = _make_pm("file:log", "file:plan")
        log_plugin = mgr.pm.get_plugin("file:log")
        plan_plugin = mgr.pm.get_plugin("file:plan")
        log_plugin.log.clear()
        
        mock_agent = MagicMock()
        mock_agent.plugin_manager = mgr
        plan_plugin.set_agent(mock_agent)
        
        plan_plugin._emit_heartbeat("execute_started",
            plan_id="p1", plan_name="Conservative", num_subtasks=5)
        plan_plugin._emit_heartbeat("subtask_started",
            plan_id="p1", subtask_id="p1-1", subtask_title="Analyze code")
        plan_plugin._emit_heartbeat("subtask_completed",
            plan_id="p1", subtask_id="p1-1", success=True)
        plan_plugin._emit_heartbeat("execute_completed",
            plan_id="p1", success=True, completed=5, failed=0, duration_s=120.5)
        
        assert len(log_plugin.log) == 4
        assert log_plugin.log[0]["plugin_event"] == "execute_started"
        assert log_plugin.log[1]["plugin_event"] == "subtask_started"
        assert log_plugin.log[2]["plugin_event"] == "subtask_completed"
        assert log_plugin.log[3]["plugin_event"] == "execute_completed"
        
        assert log_plugin.log[3]["data"]["completed"] == 5
        assert log_plugin.log[3]["data"]["duration_s"] == 120.5

    @pytest.mark.asyncio
    async def test_get_tool_log_retrieves_all_heartbeat_events(self):
        mgr = _make_pm("file:log", "file:plan")
        log_plugin = mgr.pm.get_plugin("file:log")
        plan_plugin = mgr.pm.get_plugin("file:plan")
        log_plugin.log.clear()
        
        mock_agent = MagicMock()
        mock_agent.plugin_manager = mgr
        plan_plugin.set_agent(mock_agent)
        
        plan_plugin._emit_heartbeat("generated", plan_id="p1", num_plans=2)
        plan_plugin._emit_heartbeat("scored", plan_id="p1", scores=[85, 75], recommended="p1")
        
        tools = mgr.register_tools()
        get_log_tool = next(t for t in tools if t.definition.name == "get_tool_log")
        
        result = await get_log_tool.execute()
        
        assert result.success is True
        assert result.data["count"] == 2
        
        events = [e["plugin_event"] for e in result.data["log"]]
        assert "generated" in events
        assert "scored" in events


# =============================================================================
# SoulPlugin tests
# =============================================================================

class TestSoulPluginLoading:
    def test_loads_via_manager(self):
        mgr = _make_pm("file:soul")
        assert "file:soul" in mgr.loaded_plugins

    def test_registers_three_tools(self):
        mgr = _make_pm("file:soul")
        tools = mgr.register_tools()
        tool_names = [t.definition.name for t in tools]
        assert "get_soul" in tool_names
        assert "update_soul" in tool_names
        assert "list_soul_templates" in tool_names

    def test_on_agent_start_loads_content(self):
        mgr = _make_pm("file:soul")
        plugins_dict = getattr(mgr.pm, "_name2plugin", {})
        soul_plugin = plugins_dict.get("file:soul")
        assert soul_plugin._soul_content is None

        mgr.call_on_agent_start("test input")
        assert soul_plugin._soul_content is not None
        assert "# Soul" in soul_plugin._soul_content


class TestSoulPluginDefault:
    def test_default_soul_has_required_sections(self):
        mgr = _make_pm("file:soul")
        plugins_dict = getattr(mgr.pm, "_name2plugin", {})
        soul_plugin = plugins_dict.get("file:soul")
        mgr.call_on_agent_start("")

        content = soul_plugin.get_soul()
        assert "# Soul" in content
        assert "You are a thoughtful" in content
        assert "Personality" in content
        assert "Voice & Tone" in content
        assert "Values" in content
        assert "Boundaries" in content

    def test_builtin_templates_count(self):
        from plugins.builtin.soul_plugin import BUILTIN_TEMPLATES
        assert len(BUILTIN_TEMPLATES) == 4
        assert set(BUILTIN_TEMPLATES.keys()) == {
            "default", "creative", "analytical", "senior_engineer"
        }

    def test_soul_resolution_order(self, tmp_path):
        """Local soul.md overrides global."""
        project = tmp_path / "project"
        project.mkdir()
        local_agent_dir = project / ".py-code-agent"
        local_agent_dir.mkdir()
        (local_agent_dir / "soul.md").write_text("# Soul\n\nI am LOCAL soul.\n")

        fake_home = tmp_path / "home"
        fake_home.mkdir()

        with patch.object(Path, "cwd", return_value=project):
            with patch.object(Path, "home", return_value=fake_home):
                mgr = _make_pm("file:soul")
                plugins_dict = getattr(mgr.pm, "_name2plugin", {})
                soul_plugin = plugins_dict.get("file:soul")
                mgr.call_on_agent_start("")
                content = soul_plugin.get_soul()
                assert "I am LOCAL soul" in content


class TestSoulPluginTools:
    @pytest.mark.asyncio
    async def test_get_soul_tool(self):
        mgr = _make_pm("file:soul")
        tools = mgr.register_tools()
        get_soul_tool = next(t for t in tools if t.definition.name == "get_soul")
        result = await get_soul_tool.execute()

        assert result.success is True
        assert "# Soul" in result.data["content"]
        assert "path" in result.data

    @pytest.mark.asyncio
    async def test_update_soul_tool(self, tmp_path):
        mgr = _make_pm("file:soul")
        tools = mgr.register_tools()
        update_soul_tool = next(t for t in tools if t.definition.name == "update_soul")
        save_path = tmp_path / "new_soul.md"

        result = await update_soul_tool.execute(
            content="# Soul\n\nI am a test soul.\n",
            path=str(save_path),
        )

        assert result.success is True
        assert save_path.exists()
        assert "I am a test soul" in save_path.read_text()

    @pytest.mark.asyncio
    async def test_list_soul_templates_tool(self):
        mgr = _make_pm("file:soul")
        tools = mgr.register_tools()
        list_tool = next(t for t in tools if t.definition.name == "list_soul_templates")
        result = await list_tool.execute()

        assert result.success is True
        names = result.data["templates"]
        assert len(names) == 4
        assert any(t["name"] == "default" for t in names)
        assert any(t["name"] == "senior_engineer" for t in names)


# =============================================================================
# AgentIdentityPlugin tests
# =============================================================================

class TestAgentIdentityPluginLoading:
    def test_loads_via_manager(self):
        mgr = _make_pm("file:agent_identity")
        assert "file:agent_identity" in mgr.loaded_plugins

    def test_registers_two_tools(self):
        mgr = _make_pm("file:agent_identity")
        tools = mgr.register_tools()
        tool_names = [t.definition.name for t in tools]
        assert "get_agent_identity" in tool_names
        assert "reload_agent_md" in tool_names

    def test_default_identity_content(self):
        from plugins.builtin.agent_identity_plugin import (
            AgentIdentityPlugin,
            AGENT_MD_TEMPLATE,
        )
        plugin = AgentIdentityPlugin()
        content = plugin.get_identity_content()
        assert "Py Code Agent" in content
        assert "Identity" in content
        assert content == AGENT_MD_TEMPLATE

    def test_on_agent_start_loads_identity(self):
        mgr = _make_pm("file:agent_identity")
        plugins_dict = getattr(mgr.pm, "_name2plugin", {})
        identity_plugin = plugins_dict.get("file:agent_identity")
        mgr.call_on_agent_start("Hello")
        assert identity_plugin._agent_md_content is not None
        assert "Py Code Agent" in identity_plugin._agent_md_content


class TestAgentIdentityPluginTools:
    @pytest.mark.asyncio
    async def test_get_agent_identity_tool(self):
        mgr = _make_pm("file:agent_identity")
        tools = mgr.register_tools()
        get_identity_tool = next(
            t for t in tools if t.definition.name == "get_agent_identity"
        )
        result = await get_identity_tool.execute()
        assert result.success is True
        assert "Py Code Agent" in result.data["content"]

    @pytest.mark.asyncio
    async def test_reload_agent_md_tool(self):
        mgr = _make_pm("file:agent_identity")
        tools = mgr.register_tools()
        reload_tool = next(
            t for t in tools if t.definition.name == "reload_agent_md"
        )
        result = await reload_tool.execute()
        assert result.success is True
        assert "content" in result.data


# =============================================================================
# SkillsPlugin tests
# =============================================================================

class TestSkillsPluginLoading:
    def test_loads_via_manager(self):
        mgr = _make_pm("file:skills")
        assert "file:skills" in mgr.loaded_plugins

    def test_registers_tools(self):
        mgr = _make_pm("file:skills")
        tools = mgr.register_tools()
        tool_names = [t.definition.name for t in tools]
        assert "list_skills" in tool_names
        assert "get_skill" in tool_names
        assert "search_skills" in tool_names

    def test_on_agent_start_loads_skills(self):
        mgr = _make_pm("file:skills")
        skills_plugin = mgr.pm.get_plugin("file:skills")
        assert skills_plugin is not None, "file:skills plugin not loaded"
        assert skills_plugin._loaded is False
        mgr.call_on_agent_start("hello")
        assert skills_plugin._loaded is True

    def test_hook_methods_exist(self):
        mgr = _make_pm("file:skills")
        skills_plugin = mgr.pm.get_plugin("file:skills")
        assert skills_plugin is not None
        assert hasattr(skills_plugin, "on_agent_start")
        assert hasattr(skills_plugin, "register_tools")


class TestSkillsPluginTools:
    @pytest.mark.asyncio
    async def test_list_skills_tool(self):
        mgr = _make_pm("file:skills")
        tools = mgr.register_tools()
        list_tool = next(t for t in tools if t.definition.name == "list_skills")
        result = await list_tool.execute()
        assert result.success is True
        assert "skills" in result.data
        assert "count" in result.data

    @pytest.mark.asyncio
    async def test_search_skills_tool_no_results(self):
        mgr = _make_pm("file:skills")
        tools = mgr.register_tools()
        search_tool = next(t for t in tools if t.definition.name == "search_skills")
        result = await search_tool.execute(query="nonexistent_skill_xyz_123")
        assert result.success is True
        assert result.data["count"] == 0

    @pytest.mark.asyncio
    async def test_get_skill_not_found(self):
        mgr = _make_pm("file:skills")
        tools = mgr.register_tools()
        get_tool = next(t for t in tools if t.definition.name == "get_skill")
        result = await get_tool.execute(name="nonexistent_skill_xyz")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_search_skills_with_results(self):
        """search_skills finds real skills in ~/.claude/skills/."""
        mgr = _make_pm("file:skills")
        tools = mgr.register_tools()
        search_tool = next(t for t in tools if t.definition.name == "search_skills")
        result = await search_tool.execute(query="git")
        assert result.success is True
        assert result.data["count"] >= 1, f"Expected at least 1 skill matching 'git', got {result.data}"
        # Should find gitnexus-* or git* skills
        matches = result.data["matches"]
        assert any("git" in m.lower() for m in matches), f"Expected git-related skill in {matches}"

    @pytest.mark.asyncio
    async def test_get_skill_returns_content(self):
        """get_skill returns full SKILL.md content for a real skill."""
        mgr = _make_pm("file:skills")
        tools = mgr.register_tools()
        # First list to find an available skill
        list_tool = next(t for t in tools if t.definition.name == "list_skills")
        list_result = await list_tool.execute()
        assert list_result.success is True
        skills = list_result.data.get("skills", [])
        assert len(skills) > 0, "Expected at least one skill to exist"
        skill_name = skills[0]

        # Now get its content
        get_tool = next(t for t in tools if t.definition.name == "get_skill")
        result = await get_tool.execute(name=skill_name)
        assert result.success is True
        assert "content" in result.data
        assert len(result.data["content"]) > 0
        assert result.data["name"] == skill_name
        assert "path" in result.data

    @pytest.mark.asyncio
    async def test_skill_invoke_tools_registered(self):
        """SkillsPlugin registers per-skill invoke tools (e.g. skill_find_skills)."""
        mgr = _make_pm("file:skills")
        tools = mgr.register_tools()
        tool_names = [t.definition.name for t in tools]
        # Should have at least one skill_invoke_* tool (real skills exist)
        invoke_tools = [n for n in tool_names if n.startswith("skill_")]
        assert len(invoke_tools) >= 1, (
            f"Expected at least 1 skill invoke tool, got: {tool_names[:10]}"
        )

    @pytest.mark.asyncio
    async def test_skill_invoke_tool_returns_content(self):
        """SkillInvokeTool returns the skill's SKILL.md content."""
        mgr = _make_pm("file:skills")
        tools = mgr.register_tools()
        list_tool = next(t for t in tools if t.definition.name == "list_skills")
        list_result = await list_tool.execute()
        skills = list_result.data.get("skills", [])
        assert len(skills) > 0

        # Find the invoke tool for the first skill
        skill_name = skills[0]
        invoke_tool_name = f"skill_{skill_name.replace('-', '_')}"
        invoke_tool = next(
            (t for t in tools if t.definition.name == invoke_tool_name),
            None,
        )
        assert invoke_tool is not None, f"Expected {invoke_tool_name} in {invoke_tool_name}"
        result = await invoke_tool.execute()
        assert result.success is True
        assert "content" in result.data
        assert "path" in result.data


# =============================================================================
# All 4 plugins together
# =============================================================================

class TestAllPluginsTogether:
    def test_all_four_load_simultaneously(self):
        mgr = _make_pm(
            "file:log", "file:soul", "file:agent_identity", "file:skills"
        )
        assert "file:log" in mgr.loaded_plugins
        assert "file:soul" in mgr.loaded_plugins
        assert "file:agent_identity" in mgr.loaded_plugins
        assert "file:skills" in mgr.loaded_plugins

    def test_all_tools_registered(self):
        mgr = _make_pm(
            "file:log", "file:soul", "file:agent_identity", "file:skills"
        )
        tools = mgr.register_tools()
        tool_names = {t.definition.name for t in tools}

        expected = {
            "get_tool_log",
            "get_soul",
            "update_soul",
            "list_soul_templates",
            "get_agent_identity",
            "reload_agent_md",
            "list_skills",
            "get_skill",
            "search_skills",
        }
        assert expected.issubset(tool_names), (
            f"Missing tools. Expected {expected}, got {tool_names}"
        )

    def test_hooks_fire_for_all_plugins(self):
        mgr = _make_pm(
            "file:log", "file:soul", "file:agent_identity", "file:skills"
        )
        log_plugin = mgr.pm.get_plugin("file:log")
        soul_plugin = mgr.pm.get_plugin("file:soul")
        identity_plugin = mgr.pm.get_plugin("file:agent_identity")
        skills_plugin = mgr.pm.get_plugin("file:skills")

        log_plugin.log.clear()
        mgr.call_on_agent_start("test input")

        assert len(log_plugin.log) == 1
        assert log_plugin.log[0]["event"] == "agent_start"
        assert soul_plugin._soul_content is not None
        assert identity_plugin._agent_md_content is not None
        assert skills_plugin._loaded is True

    def test_health_all_healthy(self):
        mgr = _make_pm(
            "file:log", "file:soul", "file:agent_identity", "file:skills"
        )
        health = mgr.get_health_report()
        assert health["total_loaded"] >= 4
        assert health["healthy"] >= 4
        assert health["degraded"] == 0
        assert health["disabled"] == 0

    def test_disabled_plugin_not_enabled(self):
        cfg = PluginConfig(
            enabled=[],
            disabled=["file:log"],
        )
        mgr = PluginManager(plugin_config=cfg)
        mgr.load_plugins([_plugins_builtin])
        assert mgr._is_enabled("file:log") is False


# =============================================================================
# Full Agent session integration tests (slow — litellm import)
# Run separately: pytest tests/ -m full_agent -v
# =============================================================================

class TestFullAgentSession:
    """Full integration with real Agent. Requires litellm (~14s import overhead)."""

    @pytest.mark.full_agent
    @pytest.mark.asyncio
    async def test_agent_loads_all_four_plugins(self):
        """Agent loads log, soul, agent_identity, skills plugins from config.yaml."""
        from py_code_agent.config.models import Config
        from py_code_agent.core.agent import Agent

        config = Config.from_file(str(_repo_root / "config.yaml"))
        assert "file:log" in config.plugins.enabled
        assert "file:soul" in config.plugins.enabled
        assert "file:agent_identity" in config.plugins.enabled

        agent = Agent(config)

        assert "file:log" in agent.plugin_manager.loaded_plugins
        assert "file:soul" in agent.plugin_manager.loaded_plugins
        assert "file:agent_identity" in agent.plugin_manager.loaded_plugins

        tool_names = set(agent.tools.keys())
        assert "get_tool_log" in tool_names
        assert "get_soul" in tool_names
        assert "get_agent_identity" in tool_names
        assert "list_skills" in tool_names

    @pytest.mark.full_agent
    @pytest.mark.asyncio
    async def test_plugins_hooks_fire_during_run(self):
        """LogPlugin records events when agent runs."""
        from py_code_agent.config.models import Config
        from py_code_agent.core.agent import Agent

        config = Config.from_file(str(_repo_root / "config.yaml"))
        agent = Agent(config)

        # Log plugin should have recorded agent_start from agent.run()
        plugins_dict = getattr(agent.plugin_manager.pm, "_name2plugin", {})
        log_plugin = plugins_dict.get("file:log")

        # Clear and fire a fresh agent_start
        log_plugin.log.clear()
        agent.plugin_manager.call_on_agent_start("test session")

        assert len(log_plugin.log) == 1
        assert log_plugin.log[0]["event"] == "agent_start"

        # Fire tool hooks
        agent.plugin_manager.call_before_tool_execute("read_file", {"path": "/tmp"})
        agent.plugin_manager.call_after_tool_execute(
            "read_file", {"path": "/tmp"}, {"success": True, "data": "hello"}
        )

        assert len(log_plugin.log) == 3

    @pytest.mark.full_agent
    @pytest.mark.asyncio
    async def test_soul_and_identity_tools_work(self):
        """Soul and AgentIdentity tools execute correctly in agent context."""
        from py_code_agent.config.models import Config
        from py_code_agent.core.agent import Agent

        config = Config.from_file(str(_repo_root / "config.yaml"))
        agent = Agent(config)

        # get_soul
        result = await agent.tools["get_soul"].execute()
        assert result.success is True
        assert "# Soul" in result.data["content"]
        assert "You are a thoughtful" in result.data["content"]

        # get_agent_identity
        result = await agent.tools["get_agent_identity"].execute()
        assert result.success is True
        assert "Py Code Agent" in result.data["content"]

        # list_soul_templates
        result = await agent.tools["list_soul_templates"].execute()
        assert result.success is True
        assert len(result.data["templates"]) == 4

    @pytest.mark.full_agent
    @pytest.mark.asyncio
    async def test_plugin_health_healthy(self):
        """All plugins report healthy status in full agent."""
        from py_code_agent.config.models import Config
        from py_code_agent.core.agent import Agent

        config = Config.from_file(str(_repo_root / "config.yaml"))
        agent = Agent(config)

        health = agent.plugin_manager.get_health_report()
        assert health["healthy"] >= 3, f"Not all healthy: {health}"
        assert health["disabled"] == 0, f"Plugins disabled: {health}"

    @pytest.mark.full_agent
    @pytest.mark.asyncio
    async def test_skills_plugin_full_agent_session(self):
        """SkillsPlugin tools work in a full Agent session — list, search, get, invoke."""
        from py_code_agent.config.models import Config
        from py_code_agent.core.agent import Agent

        config = Config.from_file(str(_repo_root / "config.yaml"))
        agent = Agent(config)

        # Verify skills plugin loaded
        assert "file:skills" in agent.plugin_manager.loaded_plugins, (
            f"Skills plugin not loaded. Loaded: {agent.plugin_manager.loaded_plugins}"
        )

        # Verify skills tools registered
        tool_names = set(agent.tools.keys())
        assert "list_skills" in tool_names
        assert "get_skill" in tool_names
        assert "search_skills" in tool_names

        # list_skills — should find real skills
        result = await agent.tools["list_skills"].execute()
        assert result.success is True
        assert result.data["count"] >= 1, (
            f"Expected at least 1 skill in ~/.claude/skills/, got {result.data}"
        )
        skills = result.data["skills"]
        assert len(skills) > 0

        # search_skills — find skills matching a keyword
        result = await agent.tools["search_skills"].execute(query="git")
        assert result.success is True
        assert result.data["count"] >= 1, (
            f"Expected at least 1 git-related skill, got {result.data}"
        )

        # get_skill — retrieve a specific skill's content
        skill_name = skills[0]
        result = await agent.tools["get_skill"].execute(name=skill_name)
        assert result.success is True
        assert "content" in result.data
        assert "---" in result.data["content"]  # YAML frontmatter delimiter
        assert len(result.data["content"]) > 10
        assert result.data["name"] == skill_name

        # get_skill — not found returns failure
        result = await agent.tools["get_skill"].execute(name="nonexistent_skill_xyz_abc")
        assert result.success is False

        # search_skills — no results
        result = await agent.tools["search_skills"].execute(query="zzznomatch999xyz")
        assert result.success is True
        assert result.data["count"] == 0

        # skill_invoke tools — at least one should exist
        invoke_tools = [n for n in tool_names if n.startswith("skill_")]
        assert len(invoke_tools) >= 1, (
            f"Expected skill invoke tools, got: {invoke_tools}"
        )

        # Invoke a skill and get content
        invoke_name = invoke_tools[0]
        result = await agent.tools[invoke_name].execute()
        assert result.success is True
        assert "content" in result.data
        assert "name" in result.data
        assert "path" in result.data

        # Hook fires on agent_start
        skills_plugin = agent.plugin_manager.pm.get_plugin("file:skills")
        assert skills_plugin._loaded is True, "Skills should be loaded after agent start"


class TestEnhanceToolError:
    """Tests for the enhance_tool_error hook."""

    def test_skills_plugin_enhances_skill_not_found(self):
        mgr = _make_pm("file:skills")
        result = mgr.call_enhance_tool_error(
            tool_name="skill_docx",
            arguments={"skill_name": "docx"},
            error_info={"error_type": "skill_workflow_error", "error": "Skill not found: docx", "diagnosis": "", "suggestions": []},
        )
        assert result is not None
        assert result["error_type"] == "skill_not_found"
        assert "diagnosis" in result
        assert "fix_suggestions" in result
        assert isinstance(result["fix_suggestions"], list)

    def test_skills_plugin_enhances_missing_dependency(self):
        mgr = _make_pm("file:skills")
        result = mgr.call_enhance_tool_error(
            tool_name="skill_docx",
            arguments={"skill_name": "docx"},
            error_info={"error_type": "missing_dependency", "error": "command not found: node", "diagnosis": "", "suggestions": []},
        )
        assert result is not None
        assert result["error_type"] == "docx_missing_dependency"
        assert any("npm install" in s or "python-docx" in s for s in result["fix_suggestions"])

    def test_skills_plugin_returns_none_for_unknown_error(self):
        mgr = _make_pm("file:skills")
        result = mgr.call_enhance_tool_error(
            tool_name="read_file",
            arguments={"path": "/tmp/test"},
            error_info={"error_type": "execution_error", "error": "Permission denied", "diagnosis": "", "suggestions": []},
        )
        assert result is None

    def test_plan_plugin_enhances_plan_task_json_error(self):
        mgr = _make_pm("file:plan")
        result = mgr.call_enhance_tool_error(
            tool_name="plan_task",
            arguments={"task": "do X"},
            error_info={"error_type": "execution_error", "error": "Failed to parse JSON", "diagnosis": "", "suggestions": []},
        )
        assert result is not None
        assert result["error_type"] == "plan_task_json_error"
        assert "diagnosis" in result

    def test_plan_plugin_enhances_execute_plan_deadlock(self):
        mgr = _make_pm("file:plan")
        result = mgr.call_enhance_tool_error(
            tool_name="execute_plan",
            arguments={"plan_id": "abc"},
            error_info={"error_type": "execution_error", "error": "Deadlock: unsatisfiable dependencies", "diagnosis": "", "suggestions": []},
        )
        assert result is not None
        assert result["error_type"] == "plan_deadlock"
        assert "fix_suggestions" in result

    def test_plan_plugin_returns_none_for_unknown_tool(self):
        mgr = _make_pm("file:plan")
        result = mgr.call_enhance_tool_error(
            tool_name="read_file",
            arguments={"path": "/tmp/test"},
            error_info={"error_type": "execution_error", "error": "File not found", "diagnosis": "", "suggestions": []},
        )
        assert result is None

    def test_manager_returns_none_when_no_plugins(self):
        mgr = PluginManager(plugin_config=PluginConfig(enabled=[], disabled=[]))
        result = mgr.call_enhance_tool_error(
            tool_name="read_file",
            arguments={},
            error_info={"error_type": "execution_error", "error": "test error", "diagnosis": "", "suggestions": []},
        )
        assert result is None

