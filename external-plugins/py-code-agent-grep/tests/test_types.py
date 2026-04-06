"""Tests for types module."""

from __future__ import annotations

from py_code_agent_grep.types import Match, SearchResult, SearchConfig


class TestMatch:
    def test_to_dict(self):
        m = Match(
            file="test.py",
            line=10,
            content="def foo():",
            context_before=["class A:"],
            context_after=["    pass"],
        )
        d = m.to_dict()
        assert d["file"] == "test.py"
        assert d["line"] == 10
        assert d["content"] == "def foo():"
        assert d["context_before"] == ["class A:"]
        assert d["context_after"] == ["    pass"]

    def test_empty_contexts(self):
        m = Match(file="a.py", line=1, content="x = 1")
        d = m.to_dict()
        assert d["context_before"] == []
        assert d["context_after"] == []


class TestSearchResult:
    def test_to_dict(self):
        m = Match(file="a.py", line=1, content="x = 1")
        r = SearchResult(
            pattern="x = 1",
            search_dir="/tmp",
            total_matches=1,
            files_searched=5,
            files_matched=1,
            matches=[m],
            truncated=False,
            engine="text",
        )
        d = r.to_dict()
        assert d["pattern"] == "x = 1"
        assert d["engine"] == "text"
        assert d["total_matches"] == 1
        assert len(d["matches"]) == 1
        assert not d["truncated"]

    def test_truncated_flag(self):
        r = SearchResult(
            pattern=".",
            search_dir="/tmp",
            total_matches=200,
            files_searched=10,
            files_matched=5,
            matches=[],
            truncated=True,
            engine="text",
        )
        assert r.to_dict()["truncated"]


class TestSearchConfig:
    def test_default_excludes(self):
        assert ".git" in SearchConfig.DEFAULT_EXCLUDE_DIRS
        assert "node_modules" in SearchConfig.DEFAULT_EXCLUDE_DIRS
        assert ".venv" in SearchConfig.DEFAULT_EXCLUDE_DIRS

    def test_max_results(self):
        assert SearchConfig.DEFAULT_MAX_RESULTS == 100

    def test_file_size_limits(self):
        assert SearchConfig.MAX_FILE_SIZE == 10 * 1024 * 1024
        assert SearchConfig.MAX_AST_FILE_SIZE == 2 * 1024 * 1024
