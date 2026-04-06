"""Test AiAutoRepair five-layer self-healing engine."""

import ast
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from py_code_agent.plugins.auto_repair import AiAutoRepair


class TestAiAutoRepairLayer1WrapMethod:
    """Test Layer 1: runtime method wrapping."""

    def test_wrap_nonexistent_method(self):
        class Plugin:
            pass

        ar = AiAutoRepair("test", Plugin())
        result = ar.wrap_method("does_not_exist", MagicMock())
        assert result is False

    def test_wrap_existing_method(self):
        class Plugin:
            def bad_hook(self):
                raise RuntimeError("boom")

        p = Plugin()
        ar = AiAutoRepair("test", p)
        result = ar.wrap_method("bad_hook", p.bad_hook)
        assert result is True
        assert "bad_hook" in ar._wrapped_methods

    def test_wrapped_method_raises(self):
        class Plugin:
            def bad_hook(self):
                raise RuntimeError("boom")

        p = Plugin()
        ar = AiAutoRepair("test", p)
        ar.wrap_method("bad_hook", p.bad_hook)
        ret = p.bad_hook()
        assert ret is None

    def test_double_wrap_skipped(self):
        class Plugin:
            def hook(self):
                pass

        p = Plugin()
        ar = AiAutoRepair("test", p)
        assert ar.wrap_method("hook", p.hook) is True
        assert ar.wrap_method("hook", p.hook) is True


class TestAiAutoRepairLayer2InjectStub:
    """Test Layer 2: stub injection."""

    def test_inject_stub_onto_plugin(self):
        class Plugin:
            pass

        p = Plugin()
        ar = AiAutoRepair("test", p)
        result = ar.inject_stub("on_agent_start")
        assert result is True
        assert hasattr(p, "on_agent_start")

    def test_inject_all_stubs(self):
        class Plugin:
            pass

        p = Plugin()
        ar = AiAutoRepair("test", p)
        count = ar.inject_all_stubs()
        assert count >= 6

    def test_inject_preserves_existing(self):
        class Plugin:
            def on_agent_start(self):
                return "original"

        p = Plugin()
        ar = AiAutoRepair("test", p)
        result = ar.inject_stub("on_agent_start")
        assert result is True
        assert p.on_agent_start() == "original"


class TestAiAutoRepairLayer3ImportError:
    """Test Layer 3: pip install on ImportError."""

    def test_parse_no_module_name(self):
        ar = AiAutoRepair("test", MagicMock())
        result = ar.fix_import_error(ImportError("unexpected format"))
        assert result is False

    def test_skip_core_module(self):
        ar = AiAutoRepair("test", MagicMock())
        result = ar.fix_import_error(ImportError("No module named 'py_code_agent'"))
        assert result is False

    @patch("subprocess.run")
    def test_pip_install_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        ar = AiAutoRepair("test", MagicMock())
        result = ar.fix_import_error(ImportError("No module named 'nonexistent_pkg_xyz'"))
        assert result is True
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "install" in args
        assert "nonexistent_pkg_xyz" in args

    @patch("subprocess.run")
    def test_pip_install_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="not found")
        ar = AiAutoRepair("test", MagicMock())
        result = ar.fix_import_error(ImportError("No module named 'bad_pkg'"))
        assert result is False


class TestAiAutoRepairLayer4AttributeError:
    """Test Layer 4: attribute injection."""

    def test_inject_logger_attribute(self):
        class Plugin:
            pass

        p = Plugin()
        ar = AiAutoRepair("test", p)
        result = ar.fix_attribute_error(AttributeError("'Plugin' object has no attribute 'logger'"))
        assert result is True
        assert hasattr(p, "logger")

    def test_skip_private_attribute(self):
        ar = AiAutoRepair("test", MagicMock())
        result = ar.fix_attribute_error(AttributeError("'_private'"))
        assert result is False

    def test_skip_uppercase_attribute(self):
        ar = AiAutoRepair("test", MagicMock())
        result = ar.fix_attribute_error(AttributeError("'Plugin' object has no attribute 'CONSTANT'"))
        assert result is False


class TestAiAutoRepairLayer5ASTPatch:
    """Test Layer 5: AST-patch source file."""

    def test_patch_try_except_wraps_execute(self):
        source = '''
class MyTool:
    async def execute(self, x, y):
        return x + y
'''
        tree = ast.parse(source)

        class Tool:
            pass

        ar = AiAutoRepair("test", Tool())
        result = ar._patch_try_except(source, "MyTool")
        assert result is not None
        parsed = ast.parse(result)
        # Verify the patched code contains try/except
        assert any(
            isinstance(n, ast.Try) for n in ast.walk(parsed)
        )

    def test_patch_invalid_source(self):
        ar = AiAutoRepair("test", MagicMock())
        result = ar._patch_try_except("not python code @#$", "Foo")
        assert result is None

    def test_patch_no_execute_method(self):
        source = "x = 1"
        ar = AiAutoRepair("test", MagicMock())
        result = ar._patch_try_except(source, "Foo")
        assert result is None

    def test_get_source_returns_none_for_none_module(self):
        ar = AiAutoRepair("test", MagicMock())
        path, source = ar._get_source(None)
        assert path is None
        assert source is None

    def test_sync_instance_copies_attributes(self):
        class OldTool:
            x = 1
            y = 2

        class NewTool:
            x = 10
            y = 20
            z = 30

        old = OldTool()
        ar = AiAutoRepair("test", old)
        ar._sync_instance(old, NewTool)
        assert old.x == 10
        assert old.y == 20
