"""Tests for text_engine module."""

from __future__ import annotations

from pathlib import Path

from py_code_agent_grep.text_engine import TextEngine


class TestTextEngineSearch:
    def test_search_def_pattern(self, sample_project):
        result = TextEngine.search(r"def \w+\(\)", search_dir=str(sample_project))
        assert result.total_matches == 4
        assert result.files_matched == 3
        assert result.engine == "text"

    def test_search_case_insensitive(self, sample_project):
        result = TextEngine.search("HELLO", search_dir=str(sample_project))
        assert result.total_matches >= 2

    def test_search_case_sensitive_no_match(self, sample_project):
        result = TextEngine.search("HELLO", search_dir=str(sample_project), case_sensitive=True)
        assert result.total_matches == 0

    def test_search_todo_comments(self, sample_project):
        result = TextEngine.search("TODO|FIXME", search_dir=str(sample_project))
        assert result.total_matches == 2

    def test_search_context_lines(self, sample_project):
        result = TextEngine.search(
            r"print\(",
            search_dir=str(sample_project),
            context_before=1,
            context_after=1,
        )
        for m in result.matches:
            assert len(m.context_before) >= 1

    def test_search_max_results(self, sample_project):
        result = TextEngine.search(
            r".",
            search_dir=str(sample_project),
            max_results=2,
        )
        assert len(result.matches) <= 2
        assert result.truncated

    def test_search_no_matches(self, sample_project):
        result = TextEngine.search("ZZZZNONEXISTENT", search_dir=str(sample_project))
        assert result.total_matches == 0

    def test_search_exclude_dirs(self, sample_project):
        result = TextEngine.search(
            r".",
            search_dir=str(sample_project),
            exclude_dirs=["tests"],
        )
        for m in result.matches:
            assert "tests" not in m.file

    def test_invalid_regex_raises(self, sample_project):
        import pytest

        with pytest.raises(ValueError, match="Invalid regex"):
            TextEngine.search("[invalid", search_dir=str(sample_project))


class TestTextEngineCount:
    def test_count_def_pattern(self, sample_project):
        result = TextEngine.count(r"def \w+\(\)", search_dir=str(sample_project))
        assert result["total_matches"] == 4
        assert result["engine"] == "text"

    def test_count_no_matches(self, sample_project):
        result = TextEngine.count("ZZZZNONEXISTENT", search_dir=str(sample_project))
        assert result["total_matches"] == 0

    def test_count_per_file(self, sample_project):
        result = TextEngine.count(r"def ", search_dir=str(sample_project))
        assert len(result["per_file"]) >= 3
