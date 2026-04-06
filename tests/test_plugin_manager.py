"""Test PluginManager integration: startup check_and_repair, reload_plugin, shutdown."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call
from concurrent.futures import TimeoutError as TimeoutExpired

import pytest

from py_code_agent.plugins.manager import PluginManager, PluginHealth
from py_code_agent.config.models import PluginConfig


@pytest.fixture
def pm():
    with patch("py_code_agent.plugins.manager.pluggy.PluginManager"):
        mgr = PluginManager.__new__(PluginManager)
        mgr.pm = MagicMock()
        mgr._health = {}
        mgr._plugin_names = []
        mgr._plugin_config = PluginConfig()
        mgr._loaded_modules = {}
        mgr._auto_repairers = {}
        mgr._protected_prefixes = {"py_code_agent"}
        mgr._protected_modules = set()
        mgr._hook_timeout = 5.0
        mgr._failure_threshold = 3
        mgr._disable_threshold = 5
        mgr._executor = MagicMock()
        return mgr


class TestCheckAndRepair:
    """Test startup health check and auto-repair."""

    def test_no_plugins(self, pm):
        report = pm.check_and_repair()
        assert report["total"] == 0
        assert report["healed"] == []
        assert report["reloaded"] == []
        assert report["still_disabled"] == []

    def test_heals_degraded_plugins(self, pm):
        pm._health["p1"] = PluginHealth(name="p1", failure_count=2)
        with patch.object(pm, "heal_plugin", return_value=True) as mock_heal:
            report = pm.check_and_repair()
            assert len(report["healed"]) == 1
            assert report["healed"][0]["name"] == "p1"
            assert report["healed"][0]["previous_failures"] == 2
            mock_heal.assert_called_once_with("p1")

    def test_healthy_plugins_not_touched(self, pm):
        pm._health["p1"] = MagicMock(
            name="p1",
            disabled=False,
            failure_count=0,
            is_healthy=True,
        )
        report = pm.check_and_repair()
        assert "p1" in report["already_healthy"]

    def test_fatal_disabled_not_reloaded(self, pm):
        pm._health["p1"] = MagicMock(
            name="p1",
            disabled=True,
            disabled_reason="fatal: SystemExit",
        )
        report = pm.check_and_repair()
        assert len(report["still_disabled"]) == 1
        assert report["still_disabled"][0]["action"] == "skip"

    def test_threshold_disabled_reloaded(self, pm):
        pm._health["p1"] = MagicMock(
            name="p1",
            disabled=True,
            disabled_reason="exceeded failure threshold (5)",
        )
        pm._health["p1"].name = "p1"
        pm._plugin_names = ["p1"]

        with patch.object(pm, "reload_plugin", return_value=True) as mock_reload:
            report = pm.check_and_repair()
            assert len(report["reloaded"]) == 1
            mock_reload.assert_called_once_with("p1")


class TestReloadPlugin:
    """Test plugin reload mechanism."""

    def test_reload_unknown_plugin(self, pm):
        result = pm.reload_plugin("nonexistent")
        assert result is False

    def test_skip_fatal_disabled(self, pm):
        pm._health["p1"] = MagicMock(
            name="p1",
            disabled=True,
            disabled_reason="fatal: MemoryError",
        )
        result = pm.reload_plugin("p1")
        assert result is False

    @patch("py_code_agent.plugins.manager.importlib.util.spec_from_file_location")
    @patch("py_code_agent.plugins.manager.importlib.util.module_from_spec")
    @patch("py_code_agent.plugins.manager.sys")
    def test_reload_file_plugin_missing_source(self, mock_sys, mock_mod_spec, mock_spec_from_file, pm):
        pm._health["file:missing"] = MagicMock(
            name="file:missing",
            disabled=True,
            disabled_reason="exceeded failure threshold (5)",
        )
        pm._plugin_names = ["file:missing"]
        pm._health["file:missing"].name = "file:missing"

        with patch.object(pm, "_find_plugin_file", return_value=None):
            result = pm.reload_plugin("file:missing")
        assert result is False

    def test_reload_entry_point_plugin(self, pm):
        pm._health["ep-plugin"] = MagicMock(
            name="ep-plugin",
            disabled=True,
            disabled_reason="exceeded failure threshold (5)",
        )
        pm._plugin_names = ["ep-plugin"]
        pm._health["ep-plugin"].name = "ep-plugin"

        with patch.object(pm, "heal_plugin", return_value=True) as mock_heal:
            result = pm.reload_plugin("ep-plugin")
            assert result is True
            mock_heal.assert_called_once_with("ep-plugin")


class TestSafeHookCall:
    """Test _safe_hook_call error handling and auto-repair."""

    def test_skips_disabled_plugin(self, pm):
        pm._health["p1"] = MagicMock(name="p1", disabled=True)
        func = MagicMock()
        pm._safe_hook_call("p1", func, "arg")
        func.assert_not_called()

    def test_regular_exception_counts_failure(self, pm):
        pm._health["p1"] = PluginHealth(name="p1", failure_count=0)
        pm._plugin_names = ["p1"]
        pm._auto_repairers = {}

        def bad():
            raise ValueError("boom")

        bad.__name__ = "bad"
        pm._executor = MagicMock()
        pm._executor.submit.side_effect = ValueError("boom")
        # Also patch _get_auto_repairer so it doesn't create an AiAutoRepair
        # (which would return True from wrap_method for any MagicMock plugin,
        # causing a retry and second failure increment).
        with patch.object(pm, "_get_auto_repairer", return_value=None):
            pm._safe_hook_call("p1", bad)
        assert pm._health["p1"].failure_count == 1

    def test_timeout_disables_immediately(self, pm):
        pm._health["p1"] = PluginHealth(name="p1", failure_count=0, disabled=False)
        pm._plugin_names = ["p1"]

        # Use a real callable with __name__ so _safe_hook_call doesn't crash
        def slow_hook():
            raise TimeoutExpired()

        slow_hook.__name__ = "slow_hook"

        # Set up future so result() raises TimeoutExpired
        future = MagicMock()
        future.result.side_effect = TimeoutExpired()
        pm._executor = MagicMock()
        pm._executor.submit.return_value = future

        # Patch _handle_hook_error to avoid auto-repair path
        with patch.object(pm, "_handle_hook_error", return_value=False):
            pm._safe_hook_call("p1", slow_hook)
        # _track_failure is called with immediate=True on timeout → disabled=True
        assert pm._health["p1"].disabled is True


class TestModuleProtection:
    """Test _restore_protected_modules."""

    def test_snapshot_protected_modules(self, pm):
        snapshot = pm._snapshot_protected_modules()
        assert isinstance(snapshot, set)

    def test_restore_does_not_crash(self, pm):
        pm._protected_modules = set()
        pm._restore_protected_modules()


class TestImportErrorRetry:
    """Test ImportError → pip install → retry in loading."""

    @patch("py_code_agent.plugins.manager.AiAutoRepair")
    def test_load_entry_point_import_error_fix(self, mock_ar_class, pm):
        mock_ar = MagicMock()
        mock_ar.fix_import_error.return_value = True
        mock_ar_class.return_value = mock_ar

        ep = MagicMock()
        ep.name = "test-ep"
        ep.load.side_effect = [ImportError("No module named 'foo'"), MagicMock()]

        instance = MagicMock()
        ep.load.return_value = instance

        with patch.object(pm, "_register_plugin") as mock_reg:
            pm._load_entry_point(ep)
            mock_reg.assert_called()


class TestPluginManagerConfig:
    """Test PluginManager initialization with config."""

    def test_default_thresholds(self):
        with patch("py_code_agent.plugins.manager.pluggy.PluginManager"):
            mgr = PluginManager()
            assert mgr._hook_timeout == 5.0
            assert mgr._failure_threshold == 3
            assert mgr._disable_threshold == 5

    def test_custom_thresholds(self):
        with patch("py_code_agent.plugins.manager.pluggy.PluginManager"):
            mgr = PluginManager(hook_timeout=2.0, failure_threshold=2, disable_threshold=3)
            assert mgr._hook_timeout == 2.0
            assert mgr._failure_threshold == 2
            assert mgr._disable_threshold == 3

    def test_config_fields(self):
        cfg = PluginConfig(hook_timeout=3.0, failure_threshold=4, disable_threshold=6)
        assert cfg.hook_timeout == 3.0
        assert cfg.failure_threshold == 4
        assert cfg.disable_threshold == 6


class TestCallGetSystemPrompt:
    """Test PluginManager.call_get_system_prompt() aggregation with structured markers."""

    def test_aggregates_all_enabled_plugins(self):
        with patch("py_code_agent.plugins.manager.pluggy.PluginManager"):
            mgr = PluginManager.__new__(PluginManager)
            mgr.pm = MagicMock()
            mgr._health = {}
            mgr._plugin_names = ["file:plan", "file:soul"]
            mgr._plugin_config = PluginConfig()

            # Mock plugins with get_system_prompt
            plan_plugin = MagicMock()
            plan_plugin.get_system_prompt = MagicMock(return_value="Planning guidance here")
            soul_plugin = MagicMock()
            soul_plugin.get_system_prompt = MagicMock(return_value="Soul guidance here")

            def get_plugin(name):
                if name == "file:plan":
                    return plan_plugin
                if name == "file:soul":
                    return soul_plugin
                return None

            mgr.pm.get_plugin = get_plugin
            mgr._is_enabled = MagicMock(return_value=True)

            result = mgr.call_get_system_prompt()

            assert "<!-- [PLUGIN:plan] -->" in result
            assert "<!-- [/PLUGIN:plan] -->" in result
            assert "<!-- [PLUGIN:soul] -->" in result
            assert "<!-- [/PLUGIN:soul] -->" in result
            assert "Planning guidance here" in result
            assert "Soul guidance here" in result

    def test_skips_plugins_without_get_system_prompt(self):
        with patch("py_code_agent.plugins.manager.pluggy.PluginManager"):
            mgr = PluginManager.__new__(PluginManager)
            mgr.pm = MagicMock()
            mgr._health = {}
            mgr._plugin_names = ["file:plan"]
            mgr._plugin_config = PluginConfig()

            plan_plugin = MagicMock(spec=[])  # no get_system_prompt
            mgr.pm.get_plugin = MagicMock(return_value=plan_plugin)
            mgr._is_enabled = MagicMock(return_value=True)

            result = mgr.call_get_system_prompt()
            assert result == ""

    def test_wraps_with_structured_markers(self):
        with patch("py_code_agent.plugins.manager.pluggy.PluginManager"):
            mgr = PluginManager.__new__(PluginManager)
            mgr.pm = MagicMock()
            mgr._health = {}
            mgr._plugin_names = ["file:plan"]
            mgr._plugin_config = PluginConfig()

            plan_plugin = MagicMock()
            plan_plugin.get_system_prompt = MagicMock(return_value="Use plan_task for complex tasks")
            mgr.pm.get_plugin = MagicMock(return_value=plan_plugin)
            mgr._is_enabled = MagicMock(return_value=True)

            result = mgr.call_get_system_prompt()

            # Verify structured marker format
            assert "<!-- [PLUGIN:plan] -->" in result
            assert "Use plan_task for complex tasks" in result
            assert "<!-- [/PLUGIN:plan] -->" in result

    def test_skips_disabled_plugins(self):
        with patch("py_code_agent.plugins.manager.pluggy.PluginManager"):
            mgr = PluginManager.__new__(PluginManager)
            mgr.pm = MagicMock()
            mgr._health = {}
            mgr._plugin_names = ["file:plan"]
            mgr._plugin_config = PluginConfig()

            plan_plugin = MagicMock()
            plan_plugin.get_system_prompt = MagicMock(return_value="Guidance")
            mgr.pm.get_plugin = MagicMock(return_value=plan_plugin)
            mgr._is_enabled = MagicMock(return_value=False)  # disabled

            result = mgr.call_get_system_prompt()
            assert result == ""
            plan_plugin.get_system_prompt.assert_not_called()

    def test_returns_empty_when_no_plugins(self):
        with patch("py_code_agent.plugins.manager.pluggy.PluginManager"):
            mgr = PluginManager.__new__(PluginManager)
            mgr.pm = MagicMock()
            mgr._health = {}
            mgr._plugin_names = []
            mgr._plugin_config = PluginConfig()

            result = mgr.call_get_system_prompt()
            assert result == ""

    def test_removes_file_prefix_from_tag(self):
        with patch("py_code_agent.plugins.manager.pluggy.PluginManager"):
            mgr = PluginManager.__new__(PluginManager)
            mgr.pm = MagicMock()
            mgr._health = {}
            mgr._plugin_names = ["file:my_plugin"]
            mgr._plugin_config = PluginConfig()

            plan_plugin = MagicMock()
            plan_plugin.get_system_prompt = MagicMock(return_value="Content")
            mgr.pm.get_plugin = MagicMock(return_value=plan_plugin)
            mgr._is_enabled = MagicMock(return_value=True)

            result = mgr.call_get_system_prompt()

            assert "<!-- [PLUGIN:my_plugin] -->" in result
            assert "<!-- [PLUGIN:file:my_plugin] -->" not in result


class TestShutdown:
    """Test PluginManager.shutdown()."""

    def test_shutdown_calls_executor(self):
        with patch("py_code_agent.plugins.manager.pluggy.PluginManager"):
            mgr = PluginManager()
            mgr._executor = MagicMock()
            mgr.shutdown()
            mgr._executor.shutdown.assert_called_once_with(wait=False)
