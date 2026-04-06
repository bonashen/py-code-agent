"""Test plugin health tracking and self-healing."""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch, call

from py_code_agent.plugins.manager import (
    PluginHealth,
    PluginManager,
    _FATAL_PLUGIN_EXCEPTIONS,
    _UNRECOVERABLE_PLUGIN_EXCEPTIONS,
)
from py_code_agent.config.models import PluginConfig


class TestPluginHealth:
    """Test PluginHealth dataclass."""

    def test_default_healthy(self):
        h = PluginHealth(name="test")
        assert h.is_healthy is True
        assert h.status == "HEALTHY"

    def test_failure_count_under_threshold(self):
        h = PluginHealth(name="test", failure_count=2)
        assert h.is_healthy is True
        assert h.status == "DEGRADED (failures=2)"

    def test_failure_count_at_threshold(self):
        h = PluginHealth(name="test", failure_count=3)
        assert h.is_healthy is False
        assert h.status == "DEGRADED (failures=3)"

    def test_disabled_blocks_healthy(self):
        h = PluginHealth(name="test", disabled=True)
        assert h.is_healthy is False
        assert "DISABLED" in h.status

    def test_disabled_reason_in_status(self):
        h = PluginHealth(name="test", disabled=True, disabled_reason="fatal: SystemExit")
        assert "fatal: SystemExit" in h.status

    def test_track_success_resets_nothing(self):
        h = PluginHealth(name="test", failure_count=2)
        h.success_count += 1
        h.last_success = datetime.now()
        assert h.failure_count == 2
        assert h.success_count == 1


class TestFatalExceptions:
    """Test fatal exception classification."""

    def test_system_exit_is_fatal(self):
        assert SystemExit in _FATAL_PLUGIN_EXCEPTIONS

    def test_keyboard_interrupt_is_fatal(self):
        assert KeyboardInterrupt in _FATAL_PLUGIN_EXCEPTIONS

    def test_memory_error_is_fatal(self):
        assert MemoryError in _FATAL_PLUGIN_EXCEPTIONS

    def test_recursion_error_is_fatal(self):
        assert RecursionError in _FATAL_PLUGIN_EXCEPTIONS

    def test_assertion_error_is_fatal(self):
        assert AssertionError in _FATAL_PLUGIN_EXCEPTIONS


class TestUnrecoverableExceptions:
    """Test unrecoverable exception classification."""

    def test_type_error_unrecoverable(self):
        assert TypeError in _UNRECOVERABLE_PLUGIN_EXCEPTIONS

    def test_attribute_error_unrecoverable(self):
        assert AttributeError in _UNRECOVERABLE_PLUGIN_EXCEPTIONS

    def test_name_error_unrecoverable(self):
        assert NameError in _UNRECOVERABLE_PLUGIN_EXCEPTIONS


class TestPluginManagerHealthTracking:
    """Test PluginManager health tracking."""

    @pytest.fixture
    def pm(self):
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

    def test_track_failure_first_call(self, pm):
        pm._track_failure("p1", "some error")
        assert "p1" in pm._health
        assert pm._health["p1"].failure_count == 1
        assert pm._health["p1"].last_error == "some error"
        assert pm._health["p1"].disabled is False

    def test_track_failure_increments(self, pm):
        pm._track_failure("p1", "error1")
        pm._track_failure("p1", "error2")
        assert pm._health["p1"].failure_count == 2

    def test_track_failure_at_disable_threshold(self, pm):
        for _ in range(5):
            pm._track_failure("p1", "error")
        assert pm._health["p1"].disabled is True
        assert "exceeded failure threshold" in pm._health["p1"].disabled_reason

    def test_track_failure_immediate(self, pm):
        pm._track_failure("p1", SystemExit("boom"), immediate=True)
        assert pm._health["p1"].disabled is True
        assert pm._health["p1"].disabled_reason.startswith("fatal")

    def test_track_success(self, pm):
        pm._health["p1"] = PluginHealth(name="p1", failure_count=2)
        pm._track_success("p1")
        assert pm._health["p1"].failure_count == 2
        assert pm._health["p1"].success_count == 1
        assert pm._health["p1"].last_success is not None

    def test_track_success_unknown_plugin(self, pm):
        pm._track_success("nonexistent")
        assert "nonexistent" not in pm._health


class TestPluginManagerHeal:
    """Test PluginManager heal methods."""

    @pytest.fixture
    def pm(self):
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

    def test_heal_plugin_unknown(self, pm):
        result = pm.heal_plugin("nonexistent")
        assert result is False

    def test_heal_plugin_resets_counts(self, pm):
        pm._health["p1"] = PluginHealth(
            name="p1",
            failure_count=4,
            disabled=True,
            last_error="some error",
            disabled_reason="exceeded",
        )
        result = pm.heal_plugin("p1")
        assert result is True
        assert pm._health["p1"].failure_count == 0
        assert pm._health["p1"].disabled is False
        assert pm._health["p1"].last_error is None
        assert pm._health["p1"].disabled_reason is None

    def test_heal_all(self, pm):
        pm._health["p1"] = PluginHealth(name="p1", failure_count=2)
        pm._health["p2"] = PluginHealth(name="p2", failure_count=0)
        pm._health["p3"] = PluginHealth(name="p3", failure_count=3)
        count = pm.heal_all()
        assert count == 2
        assert pm._health["p1"].failure_count == 0
        assert pm._health["p3"].failure_count == 0
        assert pm._health["p2"].failure_count == 0

    def test_disable_plugin(self, pm):
        pm._health["p1"] = PluginHealth(name="p1")
        result = pm.disable_plugin("p1", "manual disable")
        assert result is True
        assert pm._health["p1"].disabled is True
        assert pm._health["p1"].disabled_reason == "manual disable"

    def test_disable_plugin_unknown(self, pm):
        result = pm.disable_plugin("nonexistent", "reason")
        assert result is False


class TestPluginManagerHealthReport:
    """Test health report generation."""

    @pytest.fixture
    def pm(self):
        with patch("py_code_agent.plugins.manager.pluggy.PluginManager"):
            mgr = PluginManager.__new__(PluginManager)
            mgr.pm = MagicMock()
            mgr._health = {}
            mgr._plugin_names = ["p1", "p2", "p3", "p4"]
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

    def test_report_counts(self, pm):
        pm._health["p1"] = PluginHealth(name="p1")
        pm._health["p2"] = PluginHealth(name="p2", failure_count=2)
        pm._health["p3"] = PluginHealth(name="p3", disabled=True)
        pm._health["p4"] = PluginHealth(name="p4")

        report = pm.get_health_report()
        assert report["healthy"] == 3
        assert report["degraded"] == 1
        assert report["disabled"] == 1
        assert report["failure_threshold"] == 3
        assert report["disable_threshold"] == 5
