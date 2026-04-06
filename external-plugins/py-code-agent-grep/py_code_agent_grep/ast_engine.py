"""AST search engine powered by ast-grep-py (PyO3 binding)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from py_code_agent_grep.file_scanner import FileScanner
from py_code_agent_grep.types import Match, SearchConfig, SearchResult

LANG_EXTENSIONS: Dict[str, List[str]] = {
    "typescript": [".ts", ".tsx"],
    "javascript": [".js", ".jsx", ".mjs", ".cjs"],
    "python": [".py"],
    "java": [".java"],
    "go": [".go"],
    "rust": [".rs"],
    "c": [".c", ".h"],
    "cpp": [".cpp", ".hpp", ".cc", ".cxx"],
    "csharp": [".cs"],
    "ruby": [".rb"],
    "scala": [".scala"],
    "swift": [".swift"],
    "kotlin": [".kt", ".kts"],
    "php": [".php"],
    "html": [".html", ".htm"],
    "css": [".css", ".scss", ".less"],
    "yaml": [".yaml", ".yml"],
    "json": [".json"],
    "bash": [".sh", ".bash"],
    "lua": [".lua"],
    "elixir": [".ex", ".exs"],
    "haskell": [".hs"],
    "nix": [".nix"],
    "solidity": [".sol"],
}

EXT_TO_LANG: Dict[str, str] = {}
for _lang, _exts in LANG_EXTENSIONS.items():
    for _ext in _exts:
        EXT_TO_LANG[_ext] = _lang


class AstEngine:
    """AST-based search engine using ast-grep-py (PyO3 binding)."""

    @staticmethod
    def search(
        pattern: str,
        search_dir: str = ".",
        lang: Optional[str] = None,
        include: str = "*",
        exclude_dirs: Optional[List[str]] = None,
        context_before: int = 0,
        context_after: int = 0,
        max_results: int = 100,
    ) -> SearchResult:
        from ast_grep_py import SgRoot

        matches: List[Match] = []
        files_searched = 0
        files_matched_set: set[str] = set()
        total_matches = 0

        for fpath in FileScanner.discover(search_dir, include, exclude_dirs):
            file_lang = lang or _detect_language(fpath)
            if file_lang is None:
                continue

            try:
                if fpath.stat().st_size > SearchConfig.MAX_AST_FILE_SIZE:
                    continue
            except OSError:
                continue

            files_searched += 1
            file_matches = _search_file_ast(
                fpath, pattern, file_lang, context_before, context_after
            )
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
            engine="ast",
        )

    @staticmethod
    def count(
        pattern: str,
        search_dir: str = ".",
        lang: Optional[str] = None,
        include: str = "*",
        exclude_dirs: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        from ast_grep_py import SgRoot

        total = 0
        files_searched = 0
        per_file: Dict[str, int] = {}

        for fpath in FileScanner.discover(search_dir, include, exclude_dirs):
            file_lang = lang or _detect_language(fpath)
            if file_lang is None:
                continue

            try:
                if fpath.stat().st_size > SearchConfig.MAX_AST_FILE_SIZE:
                    continue
            except OSError:
                continue

            files_searched += 1
            count = _count_file_ast(fpath, pattern, file_lang)
            if count > 0:
                total += count
                per_file[str(fpath)] = count

        return {
            "total_matches": total,
            "files_searched": files_searched,
            "files_matched": len(per_file),
            "per_file": per_file,
            "engine": "ast",
        }


def _search_file_ast(
    fpath: Path,
    pattern: str,
    lang: str,
    ctx_before: int,
    ctx_after: int,
) -> List[Match]:
    from ast_grep_py import SgRoot

    try:
        content = fpath.read_text(encoding="utf-8", errors="replace")
        sg = SgRoot(content, lang)
        root = sg.root()
        all_nodes = list(root.find_all(pattern))
    except Exception:
        return []

    if not all_nodes:
        return []

    lines = content.split("\n")
    matches: List[Match] = []

    for node in all_nodes:
        start_line = node.start_pos()["line"]
        end_line = node.end_pos()["line"]
        matched_text = node.text()

        before = lines[max(0, start_line - ctx_before) : start_line]
        after = lines[end_line + 1 : end_line + 1 + ctx_after]

        matches.append(
            Match(
                file=str(fpath),
                line=start_line + 1,
                content=matched_text,
                context_before=before,
                context_after=after,
            )
        )

    return matches


def _count_file_ast(fpath: Path, pattern: str, lang: str) -> int:
    from ast_grep_py import SgRoot

    try:
        content = fpath.read_text(encoding="utf-8", errors="replace")
        sg = SgRoot(content, lang)
        root = sg.root()
        return len(list(root.find_all(pattern)))
    except Exception:
        return 0


def _detect_language(fpath: Path) -> Optional[str]:
    ext = fpath.suffix.lower()
    return EXT_TO_LANG.get(ext)
