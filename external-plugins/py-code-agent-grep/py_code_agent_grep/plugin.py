"""GrepPlugin — Unified code search for Py Code Agent."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from py_code_agent.plugins.hooks import hookimpl
from py_code_agent.tools.base import BaseTool

from py_code_agent_grep.tools import GrepCountTool, GrepSearchTool


class GrepPlugin:
    """Unified code search plugin — text regex + AST structural search.

    Dependencies:
        - ast-grep-py>=0.42.0: AST search engine (PyO3 binding)
    """

    @hookimpl
    def register_tools(self) -> List[BaseTool]:
        return [GrepSearchTool(), GrepCountTool()]

    @hookimpl
    def get_system_prompt(self) -> str:
        return """## Code Search (Grep)

Use `grep_search` as your unified search tool:
- **Text mode**: regex patterns for comments, strings, TODOs, keywords
  Example: `grep_search(pattern="TODO|FIXME")`
- **AST mode**: structural patterns with meta-variables ($VAR, $$$)
  Example: `grep_search(pattern="def $FUNC($$$):", lang="python")`
- **Auto-detect**: The engine is automatically selected based on your pattern.
  Use `$$$` or specify `lang` to trigger AST search.

Use `grep_count` for quick existence checks before full search.

Default excludes: .git, node_modules, .venv, __pycache__, dist, build
"""

    @hookimpl
    def enhance_tool_error(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        error_info: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if tool_name == "grep_search":
            error_msg = error_info.get("error", "").lower()

            if "invalid regex" in error_msg or "regex" in error_msg:
                return {
                    "error_type": "grep_invalid_regex",
                    "diagnosis": "The search pattern is not a valid regular expression.",
                    "fix_suggestions": [
                        "Check for unescaped special characters",
                        "Use raw strings: r'pattern' instead of 'pattern'",
                        "Escape dots: use '\\.' for literal dots",
                    ],
                    "confidence": 0.95,
                }

            if "ast" in error_msg or "parse" in error_msg or "syntax" in error_msg:
                return {
                    "error_type": "grep_ast_parse_error",
                    "diagnosis": "AST engine failed to parse the pattern or source file.",
                    "fix_suggestions": [
                        "Ensure pattern is a valid AST node (complete code snippet)",
                        "Meta-variables: $VAR for single node, $$$ for multiple nodes",
                        "Verify the `lang` parameter matches the file type",
                        "Try text mode: remove `lang` and use regex instead",
                    ],
                    "confidence": 0.9,
                }

            if "no matches" in error_msg or "0 matches" in error_msg:
                lang = arguments.get("lang")
                suggestions = [
                    "Try a simpler pattern",
                    "Check if include glob pattern is too restrictive",
                    "Verify search_dir exists and contains files",
                ]
                if lang:
                    suggestions.append(
                        f"AST search for '{lang}' found nothing — try text mode (remove lang parameter)"
                    )
                else:
                    suggestions.append(
                        "Try AST mode: add `lang` parameter or use meta-variables ($$$)"
                    )
                return {
                    "error_type": "grep_no_matches",
                    "diagnosis": "No matches found with the current pattern and engine.",
                    "fix_suggestions": suggestions,
                    "confidence": 0.85,
                }

        return None

    @hookimpl
    def enhance_tool_error_priority(self) -> int:
        return 50
