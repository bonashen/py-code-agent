"""Tests for EditFilePlugin."""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(_repo_root))

from py_code_agent.config.models import PluginConfig
from py_code_agent.plugins.manager import PluginManager

_plugins_builtin = _repo_root / "plugins" / "builtin"


def _make_pm(*plugin_names: str) -> PluginManager:
    cfg = PluginConfig(enabled=list(plugin_names), disabled=[])
    mgr = PluginManager(plugin_config=cfg)
    mgr.load_plugins([_plugins_builtin])
    return mgr


class TestEditFilePluginLoading:
    def test_loads_via_manager(self):
        mgr = _make_pm("file:edit_file")
        assert "file:edit_file" in mgr.loaded_plugins

    def test_registers_edit_file_tool(self):
        mgr = _make_pm("file:edit_file")
        tools = mgr.register_tools()
        tool_names = [t.definition.name for t in tools]
        assert "edit_file" in tool_names

    def test_hook_methods_exist(self):
        mgr = _make_pm("file:edit_file")
        edit_plugin = mgr.pm.get_plugin("file:edit_file")
        assert edit_plugin is not None
        assert hasattr(edit_plugin, "register_tools")
        assert hasattr(edit_plugin, "get_system_prompt")


class TestEditFilePluginSystemPrompt:
    def test_system_prompt_contains_edit_file(self):
        mgr = _make_pm("file:edit_file")
        edit_plugin = mgr.pm.get_plugin("file:edit_file")
        prompt = edit_plugin.get_system_prompt()
        assert "edit_file" in prompt
        assert "old_string" in prompt
        assert "dry_run" in prompt


class TestEditFileTool:
    @pytest.mark.asyncio
    async def test_successful_edit(self, tmp_path):
        mgr = _make_pm("file:edit_file")
        tools = mgr.register_tools()
        edit_tool = next(t for t in tools if t.definition.name == "edit_file")

        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world\nfoo bar\n")

        result = await edit_tool.execute(
            path=str(test_file),
            old_string="hello world",
            new_string="goodbye world",
        )

        assert result.success is True
        assert result.data["replaced"] == 1
        assert "goodbye world" in test_file.read_text()

    @pytest.mark.asyncio
    async def test_edit_with_multiline_old_string(self, tmp_path):
        mgr = _make_pm("file:edit_file")
        tools = mgr.register_tools()
        edit_tool = next(t for t in tools if t.definition.name == "edit_file")

        test_file = tmp_path / "test.py"
        test_file.write_text("def foo():\n    pass\n\ndef bar():\n    pass\n")

        result = await edit_tool.execute(
            path=str(test_file),
            old_string="def foo():\n    pass",
            new_string="def foo():\n    return 42",
        )

        assert result.success is True
        content = test_file.read_text()
        assert "return 42" in content
        assert "def bar():" in content

    @pytest.mark.asyncio
    async def test_file_not_found(self):
        mgr = _make_pm("file:edit_file")
        tools = mgr.register_tools()
        edit_tool = next(t for t in tools if t.definition.name == "edit_file")

        result = await edit_tool.execute(
            path="/nonexistent/file.txt",
            old_string="something",
            new_string="else",
        )

        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_string_not_found(self, tmp_path):
        mgr = _make_pm("file:edit_file")
        tools = mgr.register_tools()
        edit_tool = next(t for t in tools if t.definition.name == "edit_file")

        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world\n")

        result = await edit_tool.execute(
            path=str(test_file),
            old_string="nonexistent string xyz",
            new_string="replacement",
        )

        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_replace_second_occurrence(self, tmp_path):
        mgr = _make_pm("file:edit_file")
        tools = mgr.register_tools()
        edit_tool = next(t for t in tools if t.definition.name == "edit_file")

        test_file = tmp_path / "test.txt"
        test_file.write_text("foo\nfoo\nfoo\n")

        result = await edit_tool.execute(
            path=str(test_file),
            old_string="foo",
            new_string="bar",
            occurrence=2,
        )

        assert result.success is True
        content = test_file.read_text()
        assert content == "foo\nbar\nfoo\n"

    @pytest.mark.asyncio
    async def test_replace_all_occurrences(self, tmp_path):
        mgr = _make_pm("file:edit_file")
        tools = mgr.register_tools()
        edit_tool = next(t for t in tools if t.definition.name == "edit_file")

        test_file = tmp_path / "test.txt"
        test_file.write_text("foo\nfoo\nfoo\n")

        result = await edit_tool.execute(
            path=str(test_file),
            old_string="foo",
            new_string="bar",
            occurrence=-1,
        )

        assert result.success is True
        assert result.data["replaced"] == 3
        assert test_file.read_text() == "bar\nbar\nbar\n"

    @pytest.mark.asyncio
    async def test_occurrence_out_of_range(self, tmp_path):
        mgr = _make_pm("file:edit_file")
        tools = mgr.register_tools()
        edit_tool = next(t for t in tools if t.definition.name == "edit_file")

        test_file = tmp_path / "test.txt"
        test_file.write_text("foo\n")

        result = await edit_tool.execute(
            path=str(test_file),
            old_string="foo",
            new_string="bar",
            occurrence=5,
        )

        assert result.success is False
        assert "out of range" in result.error.lower()

    @pytest.mark.asyncio
    async def test_dry_run(self, tmp_path):
        mgr = _make_pm("file:edit_file")
        tools = mgr.register_tools()
        edit_tool = next(t for t in tools if t.definition.name == "edit_file")

        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world\n")

        result = await edit_tool.execute(
            path=str(test_file),
            old_string="hello world",
            new_string="goodbye world",
            dry_run=True,
        )

        assert result.success is True
        assert result.data["would_replace"] == 1
        assert "preview" in result.data
        assert "hello world" in result.data["preview"]
        assert "goodbye world" in result.data["preview"]
        assert test_file.read_text() == "hello world\n"

    @pytest.mark.asyncio
    async def test_dry_run_multiple_occurrences(self, tmp_path):
        mgr = _make_pm("file:edit_file")
        tools = mgr.register_tools()
        edit_tool = next(t for t in tools if t.definition.name == "edit_file")

        test_file = tmp_path / "test.txt"
        test_file.write_text("foo\nfoo\nfoo\n")

        result = await edit_tool.execute(
            path=str(test_file),
            old_string="foo",
            new_string="bar",
            occurrence=-1,
            dry_run=True,
        )

        assert result.success is True
        assert result.data["would_replace"] == 3
        assert test_file.read_text() == "foo\nfoo\nfoo\n"

    @pytest.mark.asyncio
    async def test_path_validation_blocked(self, tmp_path):
        mgr = _make_pm("file:edit_file")
        edit_plugin = mgr.pm.get_plugin("file:edit_file")
        edit_plugin.configure(blocked_paths=[str(tmp_path)])

        tools = mgr.register_tools()
        edit_tool = next(t for t in tools if t.definition.name == "edit_file")

        test_file = tmp_path / "test.txt"
        test_file.write_text("content\n")

        result = await edit_tool.execute(
            path=str(test_file),
            old_string="content",
            new_string="new",
        )

        assert result.success is False
        assert "blocked" in result.error.lower()

    @pytest.mark.asyncio
    async def test_path_validation_allowed(self, tmp_path):
        mgr = _make_pm("file:edit_file")
        edit_plugin = mgr.pm.get_plugin("file:edit_file")
        edit_plugin.configure(allowed_paths=[str(tmp_path)])

        tools = mgr.register_tools()
        edit_tool = next(t for t in tools if t.definition.name == "edit_file")

        test_file = tmp_path / "test.txt"
        test_file.write_text("content\n")

        result = await edit_tool.execute(
            path=str(test_file),
            old_string="content",
            new_string="new",
        )

        assert result.success is True

    @pytest.mark.asyncio
    async def test_path_validation_not_in_allowed(self, tmp_path):
        mgr = _make_pm("file:edit_file")
        edit_plugin = mgr.pm.get_plugin("file:edit_file")
        other_dir = tmp_path / "other"
        other_dir.mkdir()
        edit_plugin.configure(allowed_paths=[str(tmp_path / "allowed")])

        tools = mgr.register_tools()
        edit_tool = next(t for t in tools if t.definition.name == "edit_file")

        test_file = other_dir / "test.txt"
        test_file.write_text("content\n")

        result = await edit_tool.execute(
            path=str(test_file),
            old_string="content",
            new_string="new",
        )

        assert result.success is False
        assert "not in allowed" in result.error.lower()

    @pytest.mark.asyncio
    async def test_binary_file(self, tmp_path):
        mgr = _make_pm("file:edit_file")
        tools = mgr.register_tools()
        edit_tool = next(t for t in tools if t.definition.name == "edit_file")

        test_file = tmp_path / "test.bin"
        test_file.write_bytes(b"\x80\x81\x82\x83\xff\xfe")

        result = await edit_tool.execute(
            path=str(test_file),
            old_string="\x80",
            new_string="\xff",
        )

        assert result.success is False
        assert "binary" in result.error.lower()

    @pytest.mark.asyncio
    async def test_not_a_file(self, tmp_path):
        mgr = _make_pm("file:edit_file")
        tools = mgr.register_tools()
        edit_tool = next(t for t in tools if t.definition.name == "edit_file")

        test_dir = tmp_path / "subdir"
        test_dir.mkdir()

        result = await edit_tool.execute(
            path=str(test_dir),
            old_string="something",
            new_string="else",
        )

        assert result.success is False
        assert "not a file" in result.error.lower()

    @pytest.mark.asyncio
    async def test_summary_contains_useful_info(self, tmp_path):
        mgr = _make_pm("file:edit_file")
        tools = mgr.register_tools()
        edit_tool = next(t for t in tools if t.definition.name == "edit_file")

        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world\n")

        result = await edit_tool.execute(
            path=str(test_file),
            old_string="hello world",
            new_string="goodbye",
        )

        assert result.summary is not None
        assert "Replaced" in result.summary
        assert "test.txt" in result.summary
