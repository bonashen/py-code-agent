"""File discovery with glob filtering and directory exclusion."""

from __future__ import annotations

import os
from fnmatch import fnmatch
from pathlib import Path
from typing import Iterator, List, Optional, Set

from py_code_agent_grep.types import SearchConfig


class FileScanner:
    """Discover files matching include/exclude patterns.

    Walks a directory tree, applies glob-based file filtering
    and directory exclusion to produce an iterator of candidate
    files for search engines.
    """

    @staticmethod
    def discover(
        search_dir: str,
        include: str = "*",
        exclude_dirs: Optional[List[str]] = None,
    ) -> Iterator[Path]:
        """Yield file paths that match the include pattern and are not in excluded dirs.

        Args:
            search_dir: Root directory to start scanning from.
            include: Glob pattern to filter files (supports brace expansion).
            exclude_dirs: Directory names to skip during traversal.

        Yields:
            Path objects for files that pass all filters.
        """
        base = Path(search_dir).resolve()
        if not base.is_dir():
            return

        excludes: Set[str] = set(exclude_dirs or SearchConfig.DEFAULT_EXCLUDE_DIRS)

        for root, dirs, files in os.walk(base):
            # Prune excluded directories in-place to prevent os.walk from descending
            dirs[:] = [d for d in dirs if d not in excludes]

            for fname in files:
                fpath = Path(root) / fname

                # Apply include glob filter
                if not _match_glob(fpath.name, include):
                    continue

                # Skip files exceeding size limit
                try:
                    if fpath.stat().st_size > SearchConfig.MAX_FILE_SIZE:
                        continue
                except OSError:
                    continue

                yield fpath


def _match_glob(filename: str, pattern: str) -> bool:
    """Match a filename against a glob pattern with brace expansion support.

    Handles patterns like '*.{py,ts}' by expanding to '*.py' and '*.ts'.

    Args:
        filename: The filename to test.
        pattern: Glob pattern, optionally with brace expansion.

    Returns:
        True if the filename matches the pattern.
    """
    # Handle brace expansion: *.{py,ts} → *.py, *.ts
    if "{" in pattern and "}" in pattern:
        import re

        match = re.match(r"(.*)\{(.+)\}(.*)", pattern)
        if match:
            prefix, alternatives, suffix = match.groups()
            for alt in alternatives.split(","):
                if fnmatch(filename, f"{prefix}{alt.strip()}{suffix}"):
                    return True
            return False

    return fnmatch(filename, pattern)
