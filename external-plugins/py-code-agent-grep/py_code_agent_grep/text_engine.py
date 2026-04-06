"""Text-based search engine — regex line-by-line scanning."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Pattern

from py_code_agent_grep.file_scanner import FileScanner
from py_code_agent_grep.types import Match, SearchResult


class TextEngine:
    """Regex-based text search engine. Zero external dependencies."""

    @staticmethod
    def search(
        pattern: str,
        search_dir: str = ".",
        include: str = "*",
        exclude_dirs: Optional[List[str]] = None,
        case_sensitive: bool = False,
        context_before: int = 0,
        context_after: int = 0,
        max_results: int = 100,
    ) -> SearchResult:
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            compiled = re.compile(pattern, flags)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern: {e}")

        matches: List[Match] = []
        files_searched = 0
        files_matched_set: set[str] = set()
        total_matches = 0

        for fpath in FileScanner.discover(search_dir, include, exclude_dirs):
            files_searched += 1
            file_matches = _search_file(fpath, compiled, context_before, context_after)
            if file_matches:
                files_matched_set.add(str(fpath))
                for m in file_matches:
                    total_matches += 1
                    if len(matches) < max_results:
                        matches.append(m)

        return SearchResult(
            pattern=pattern,
            search_dir=str(Path(search_dir).resolve()),
            total_matches=total_matches,
            files_searched=files_searched,
            files_matched=len(files_matched_set),
            matches=matches,
            truncated=total_matches > max_results,
            engine="text",
        )

    @staticmethod
    def count(
        pattern: str,
        search_dir: str = ".",
        include: str = "*",
        exclude_dirs: Optional[List[str]] = None,
        case_sensitive: bool = False,
    ) -> Dict[str, Any]:
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            compiled = re.compile(pattern, flags)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern: {e}")

        total = 0
        files_searched = 0
        per_file: Dict[str, int] = {}

        for fpath in FileScanner.discover(search_dir, include, exclude_dirs):
            files_searched += 1
            count = 0
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if compiled.search(line):
                            count += 1
            except (OSError, UnicodeDecodeError):
                continue

            if count > 0:
                total += count
                per_file[str(fpath)] = count

        return {
            "total_matches": total,
            "files_searched": files_searched,
            "files_matched": len(per_file),
            "per_file": per_file,
            "engine": "text",
        }


def _search_file(
    fpath: Path,
    compiled: Pattern[str],
    ctx_before: int,
    ctx_after: int,
) -> List[Match]:
    try:
        with open(fpath, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except (OSError, UnicodeDecodeError):
        return []

    matches: List[Match] = []
    for i, line in enumerate(lines):
        if compiled.search(line):
            before = [l.rstrip("\n") for l in lines[max(0, i - ctx_before) : i]]
            after = [l.rstrip("\n") for l in lines[i + 1 : i + 1 + ctx_after]]
            matches.append(
                Match(
                    file=str(fpath),
                    line=i + 1,
                    content=line.rstrip("\n"),
                    context_before=before,
                    context_after=after,
                )
            )

    return matches
