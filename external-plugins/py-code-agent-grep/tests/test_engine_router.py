"""Tests for engine_router module."""

from __future__ import annotations

from py_code_agent_grep.engine_router import EngineRouter


class TestEngineRouter:
    def test_meta_variable_triggers_ast(self):
        assert EngineRouter.select("def $FUNC($$$):") == "ast"
        assert EngineRouter.select("console.log($$$)") == "ast"
        assert EngineRouter.select("$VAR") == "ast"

    def test_lang_forces_ast(self):
        assert EngineRouter.select("def hello()", lang="python") == "ast"
        assert EngineRouter.select("anything", lang="typescript") == "ast"

    def test_non_code_files_use_text(self):
        assert EngineRouter.select(".*", include="*.md") == "text"
        assert EngineRouter.select(".*", include="*.txt") == "text"
        assert EngineRouter.select(".*", include="*.log") == "text"

    def test_comment_hints_use_text(self):
        assert EngineRouter.select("TODO|FIXME") == "text"
        assert EngineRouter.select("HACK") == "text"

    def test_default_is_text(self):
        assert EngineRouter.select("def test_") == "text"
        assert EngineRouter.select("import os") == "text"
        assert EngineRouter.select("console.log") == "text"
