"""Tool implementations for GrepPlugin."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from py_code_agent.tools.base import (
    BaseTool,
    ToolDefinition,
    ToolParameter,
    ToolParameterType,
    ToolResult,
)

from py_code_agent_grep.engine import SearchEngine


class GrepSearchTool(BaseTool):
    """Unified code search with auto engine selection."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="grep_search",
            description=(
                "Unified code search — supports both regex text search and AST structural search. "
                "Engine is automatically selected: meta-variables ($$$) or `lang` → AST, otherwise text."
            ),
            parameters=[
                ToolParameter(
                    name="pattern",
                    type=ToolParameterType.STRING,
                    description=(
                        "Search pattern. Text mode: standard regex (e.g., 'def test_', 'TODO|FIXME'). "
                        "AST mode: structural patterns with meta-variables (e.g., 'def $FUNC($$$):')."
                    ),
                    required=True,
                ),
                ToolParameter(
                    name="lang",
                    type=ToolParameterType.STRING,
                    description=(
                        "Programming language for AST search. Forces AST engine. "
                        "Supported: python, typescript, javascript, java, go, rust, c, cpp, csharp, "
                        "ruby, scala, swift, kotlin, php, html, css, yaml, json, bash, lua, elixir, "
                        "haskell, nix, solidity."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="search_dir",
                    type=ToolParameterType.STRING,
                    description="Directory to search. Default: '.'",
                    required=False,
                    default=".",
                ),
                ToolParameter(
                    name="include",
                    type=ToolParameterType.STRING,
                    description="Glob pattern to filter files. Default: '*'. Supports brace expansion: '*.{py,ts}'",
                    required=False,
                    default="*",
                ),
                ToolParameter(
                    name="exclude_dirs",
                    type=ToolParameterType.ARRAY,
                    description=(
                        "Directories to exclude. "
                        "Default: ['.git', 'node_modules', '.venv', '__pycache__', 'dist', 'build']"
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="case_sensitive",
                    type=ToolParameterType.BOOLEAN,
                    description="Case sensitive search (text mode only). Default: False.",
                    required=False,
                    default=False,
                ),
                ToolParameter(
                    name="context_before",
                    type=ToolParameterType.INTEGER,
                    description="Lines before each match. Default: 0.",
                    required=False,
                    default=0,
                ),
                ToolParameter(
                    name="context_after",
                    type=ToolParameterType.INTEGER,
                    description="Lines after each match. Default: 0.",
                    required=False,
                    default=0,
                ),
                ToolParameter(
                    name="max_results",
                    type=ToolParameterType.INTEGER,
                    description="Max matches to return. Default: 100.",
                    required=False,
                    default=100,
                ),
            ],
        )

    async def execute(
        self,
        pattern: str,
        lang: Optional[str] = None,
        search_dir: str = ".",
        include: str = "*",
        exclude_dirs: Optional[List[str]] = None,
        case_sensitive: bool = False,
        context_before: int = 0,
        context_after: int = 0,
        max_results: int = 100,
        **kwargs: Any,
    ) -> ToolResult:
        try:
            result = SearchEngine.search(
                pattern=pattern,
                search_dir=search_dir,
                lang=lang,
                include=include,
                exclude_dirs=exclude_dirs,
                case_sensitive=case_sensitive,
                context_before=context_before,
                context_after=context_after,
                max_results=max_results,
            )

            if result.total_matches == 0:
                return ToolResult.fail(
                    f"No matches for pattern '{pattern}' ({result.engine} engine, "
                    f"{result.files_searched} files searched)"
                )

            summary = (
                f"Found {result.total_matches} matches across "
                f"{result.files_matched} files ({result.engine} engine, "
                f"{result.files_searched} searched)"
            )
            if result.truncated:
                summary += f" (showing first {max_results})"

            return ToolResult.ok(data=result.to_dict(), summary=summary)

        except ValueError as e:
            return ToolResult.fail(f"Invalid pattern: {e}")
        except Exception as e:
            return ToolResult.fail(f"Search error: {e}")


class GrepCountTool(BaseTool):
    """Quick match count with auto engine selection."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="grep_count",
            description=(
                "Quickly count pattern matches. Use BEFORE grep_search to check if a pattern exists. "
                "Supports both text (regex) and AST (structural) modes."
            ),
            parameters=[
                ToolParameter(
                    name="pattern",
                    type=ToolParameterType.STRING,
                    description="Search pattern (regex or AST meta-variable pattern)",
                    required=True,
                ),
                ToolParameter(
                    name="lang",
                    type=ToolParameterType.STRING,
                    description="Programming language for AST search. Forces AST engine.",
                    required=False,
                ),
                ToolParameter(
                    name="search_dir",
                    type=ToolParameterType.STRING,
                    description="Directory to search. Default: '.'",
                    required=False,
                    default=".",
                ),
                ToolParameter(
                    name="include",
                    type=ToolParameterType.STRING,
                    description="Glob pattern to filter files. Default: '*'",
                    required=False,
                    default="*",
                ),
                ToolParameter(
                    name="case_sensitive",
                    type=ToolParameterType.BOOLEAN,
                    description="Case sensitive search (text mode only). Default: False.",
                    required=False,
                    default=False,
                ),
            ],
        )

    async def execute(
        self,
        pattern: str,
        lang: Optional[str] = None,
        search_dir: str = ".",
        include: str = "*",
        case_sensitive: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        try:
            result = SearchEngine.count(
                pattern=pattern,
                search_dir=search_dir,
                lang=lang,
                include=include,
                case_sensitive=case_sensitive,
            )

            if result["total_matches"] == 0:
                return ToolResult.fail(
                    f"No matches for '{pattern}' ({result.get('engine', 'text')} engine, "
                    f"{result['files_searched']} files searched)"
                )

            summary = f"{result['total_matches']} matches in {result['files_matched']} files"
            return ToolResult.ok(data=result, summary=summary)

        except ValueError as e:
            return ToolResult.fail(f"Invalid pattern: {e}")
        except Exception as e:
            return ToolResult.fail(f"Count error: {e}")
