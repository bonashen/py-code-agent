"""Data types for GrepPlugin search results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class Match:
    """Single match result (unified for both engines)."""

    file: str
    line: int
    content: str
    context_before: List[str] = field(default_factory=list)
    context_after: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file": self.file,
            "line": self.line,
            "content": self.content,
            "context_before": self.context_before,
            "context_after": self.context_after,
        }


@dataclass
class SearchResult:
    """Complete search result."""

    pattern: str
    search_dir: str
    total_matches: int
    files_searched: int
    files_matched: int
    matches: List[Match]
    truncated: bool = False
    engine: str = "text"  # "text" | "ast"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern": self.pattern,
            "search_dir": self.search_dir,
            "engine": self.engine,
            "total_matches": self.total_matches,
            "files_searched": self.files_searched,
            "files_matched": self.files_matched,
            "matches": [m.to_dict() for m in self.matches],
            "truncated": self.truncated,
        }


class SearchConfig:
    """Search configuration constants."""

    DEFAULT_EXCLUDE_DIRS: List[str] = [
        ".git",
        "node_modules",
        ".venv",
        "__pycache__",
        "dist",
        "build",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "venv",
        "env",
    ]

    DEFAULT_MAX_RESULTS: int = 100
    DEFAULT_TIMEOUT: float = 10.0
    MAX_FILE_SIZE: int = 10 * 1024 * 1024  # 10MB
    MAX_AST_FILE_SIZE: int = 2 * 1024 * 1024  # 2MB
