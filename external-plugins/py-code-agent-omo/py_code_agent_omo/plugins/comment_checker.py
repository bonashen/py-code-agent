"""Comment Checker Plugin — prevents AI-generated excessive comments."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from py_code_agent.plugins.hooks import hookimpl
from py_code_agent.tools.base import (
    BaseTool,
    ToolDefinition,
    ToolParameter,
    ToolParameterType,
    ToolResult,
)

from py_code_agent_omo.config import get_omo_config


class CommentCheckerPlugin:
    """Scans written files for excessive comment ratios.

    Flags files where comments exceed the configured threshold and
    stores the flag in ContextPlugin for the LLM to see.
    """

    COMMENT_PATTERNS = [
        r"^\s*#\s+(This function|This method|This class|This code)",
        r"^\s*#\s+(The following|Here we|Now we|In this)",
        r'^\s*"""\s*(This function|This method|This class)',
        r"^\s*//\s+(This function|This method|This is)",
    ]

    def __init__(self) -> None:
        self._agent_ref: Any = None
        self._flagged_files: List[Dict[str, Any]] = []
        self._config = get_omo_config()

    def set_agent(self, agent: Any) -> None:
        self._agent_ref = agent

    @hookimpl
    def register_tools(self) -> List[BaseTool]:
        return [CheckCommentRatioTool(self)]

    @hookimpl
    def after_tool_execute(self, tool_name: str, arguments: Dict[str, Any], result: Any) -> None:
        if tool_name not in ("write_file", "execute_bash"):
            return

        path = ""
        if tool_name == "write_file":
            path = arguments.get("path", "") or ""
        elif tool_name == "execute_bash":
            command = arguments.get("command", "") or ""
            match = re.search(r">\s*(\S+)", command)
            if match:
                path = match.group(1)

        if not path:
            return

        code_extensions = (".py", ".js", ".ts", ".tsx", ".go", ".rs", ".css")
        if not any(path.endswith(ext) for ext in code_extensions):
            return

        self._check_comment_ratio(path)

    def _is_comment(self, line: str) -> bool:
        line = line.strip()
        if not line:
            return False
        for pattern in self.COMMENT_PATTERNS:
            if re.match(pattern, line):
                return True
        if line.startswith("#") or line.startswith("//") or line.startswith("/*"):
            return True
        return False

    def _check_comment_ratio(self, path: str) -> None:
        try:
            content = Path(path).read_text(encoding="utf-8")
        except Exception:
            return

        lines = content.splitlines()
        if len(lines) < 10:
            return

        comment_lines = sum(1 for l in lines if self._is_comment(l))
        ratio = comment_lines / len(lines)

        cc_cfg = self._config.discipline.get("comment_checker", {})
        max_ratio = cc_cfg.get("max_comment_ratio", 0.15)

        if ratio > max_ratio:
            self._flagged_files.append({"path": path, "ratio": ratio, "lines": len(lines)})
            if self._agent_ref:
                pm = getattr(self._agent_ref, "plugin_manager", None)
                if pm:
                    ctx = pm.pm.get_plugin("file:context")
                    if ctx and hasattr(ctx, "write"):
                        ctx.write(
                            f"comment_flag_{path}",
                            f"Excessive comments in {path}: {ratio:.0%} ratio (threshold: {max_ratio:.0%})",
                        )

    @hookimpl
    def get_system_prompt(self) -> str:
        cc_cfg = self._config.discipline.get("comment_checker", {})
        max_ratio = cc_cfg.get("max_comment_ratio", 0.15)
        return f"""## Comment Guidelines

Write code like a senior engineer:
- Comments explain WHY, not WHAT (code should be self-documenting)
- No "This function does X" comments
- No excessive docstrings for simple methods
- Comment ratio should stay below {max_ratio:.0%}
- If you need to explain complex logic, use meaningful variable/function names instead"""


class CheckCommentRatioTool(BaseTool):
    def __init__(self, plugin: CommentCheckerPlugin) -> None:
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="check_comment_ratio",
            description="Check comment ratio for a file. Returns ratio and whether it exceeds the threshold.",
            parameters=[
                ToolParameter(
                    name="path",
                    type=ToolParameterType.STRING,
                    description="File path to check",
                    required=True,
                ),
            ],
        )

    async def execute(self, path: str, **kwargs: Any) -> ToolResult:
        try:
            content = Path(path).read_text(encoding="utf-8")
        except Exception as e:
            return ToolResult.fail(f"Cannot read file: {e}")

        lines = content.splitlines()
        comment_lines = sum(1 for l in lines if self._plugin._is_comment(l))
        ratio = comment_lines / max(len(lines), 1)

        cc_cfg = self._plugin._config.discipline.get("comment_checker", {})
        max_ratio = cc_cfg.get("max_comment_ratio", 0.15)

        return ToolResult.ok(
            data={
                "path": path,
                "ratio": ratio,
                "comment_lines": comment_lines,
                "total_lines": len(lines),
                "exceeds_threshold": ratio > max_ratio,
            },
            summary=(
                f"Comment ratio: {ratio:.0%} "
                f"({'exceeds' if ratio > max_ratio else 'within'} {max_ratio:.0%} threshold)"
            ),
        )
