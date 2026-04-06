"""Unified search engine — routes between TextEngine and AstEngine."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from py_code_agent_grep.ast_engine import AstEngine
from py_code_agent_grep.engine_router import EngineRouter
from py_code_agent_grep.text_engine import TextEngine
from py_code_agent_grep.types import SearchResult


class SearchEngine:
    """Unified search interface with automatic engine selection."""

    @staticmethod
    def search(
        pattern: str,
        search_dir: str = ".",
        lang: Optional[str] = None,
        include: str = "*",
        exclude_dirs: Optional[List[str]] = None,
        case_sensitive: bool = False,
        context_before: int = 0,
        context_after: int = 0,
        max_results: int = 100,
    ) -> SearchResult:
        engine = EngineRouter.select(pattern, lang, include)

        if engine == "ast":
            return AstEngine.search(
                pattern=pattern,
                search_dir=search_dir,
                lang=lang,
                include=include,
                exclude_dirs=exclude_dirs,
                context_before=context_before,
                context_after=context_after,
                max_results=max_results,
            )
        else:
            return TextEngine.search(
                pattern=pattern,
                search_dir=search_dir,
                include=include,
                exclude_dirs=exclude_dirs,
                case_sensitive=case_sensitive,
                context_before=context_before,
                context_after=context_after,
                max_results=max_results,
            )

    @staticmethod
    def count(
        pattern: str,
        search_dir: str = ".",
        lang: Optional[str] = None,
        include: str = "*",
        exclude_dirs: Optional[List[str]] = None,
        case_sensitive: bool = False,
    ) -> Dict[str, Any]:
        engine = EngineRouter.select(pattern, lang, include)

        if engine == "ast":
            return AstEngine.count(
                pattern=pattern,
                search_dir=search_dir,
                lang=lang,
                include=include,
                exclude_dirs=exclude_dirs,
            )
        else:
            return TextEngine.count(
                pattern=pattern,
                search_dir=search_dir,
                include=include,
                exclude_dirs=exclude_dirs,
                case_sensitive=case_sensitive,
            )
