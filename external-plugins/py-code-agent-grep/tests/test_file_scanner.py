"""Tests for file_scanner module."""

from __future__ import annotations

from pathlib import Path

from py_code_agent_grep.file_scanner import FileScanner, _match_glob


class TestMatchGlob:
    def test_simple_match(self):
        assert _match_glob("test.py", "*.py")

    def test_simple_no_match(self):
        assert not _match_glob("test.js", "*.py")

    def test_star_matches_all(self):
        assert _match_glob("anything.txt", "*")

    def test_brace_expansion(self):
        assert _match_glob("test.py", "*.{py,ts}")
        assert _match_glob("test.ts", "*.{py,ts}")
        assert not _match_glob("test.js", "*.{py,ts}")

    def test_brace_expansion_three_ways(self):
        assert _match_glob("a.py", "*.{py,ts,js}")
        assert _match_glob("a.ts", "*.{py,ts,js}")
        assert _match_glob("a.js", "*.{py,ts,js}")
        assert not _match_glob("a.go", "*.{py,ts,js}")


class TestFileScanner:
    def test_discover_all_files(self, sample_project):
        files = list(FileScanner.discover(str(sample_project)))
        assert len(files) >= 4

    def test_exclude_git_and_node_modules(self, sample_project):
        files = list(FileScanner.discover(str(sample_project)))
        for f in files:
            assert ".git" not in str(f)
            assert "node_modules" not in str(f)

    def test_glob_filter_py_only(self, sample_project):
        files = list(FileScanner.discover(str(sample_project), include="*.py"))
        for f in files:
            assert f.suffix == ".py"

    def test_glob_filter_ts_only(self, ts_project):
        files = list(FileScanner.discover(str(ts_project), include="*.ts"))
        for f in files:
            assert f.suffix == ".ts"

    def test_glob_filter_brace_expansion(self, sample_project):
        files = list(FileScanner.discover(str(sample_project), include="*.{py,md}"))
        for f in files:
            assert f.suffix in (".py", ".md")

    def test_nonexistent_dir(self, tmp_path):
        files = list(FileScanner.discover(str(tmp_path / "nonexistent")))
        assert files == []

    def test_custom_exclude_dirs(self, sample_project):
        files = list(FileScanner.discover(str(sample_project), exclude_dirs=["tests"]))
        for f in files:
            assert "tests" not in str(f)
