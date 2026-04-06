"""Edit File Plugin — precise file editing with search/replace.

Provides a single tool:
- edit_file: Replace specific content in a file with new content

Features:
- Path validation (allowed/blocked paths)
- Exact string matching with occurrence counting
- Multiple occurrence handling (first, all, or by index)
- Dry-run mode to preview changes
- Backup support before editing
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiofiles

from py_code_agent.plugins.hooks import hookimpl
from py_code_agent.tools.base import (
    BaseTool,
    ToolDefinition,
    ToolParameter,
    ToolParameterType,
    ToolResult,
)

logger = logging.getLogger(__name__)


class EditFilePlugin:
    """Plugin for precise file editing.

    Provides an edit_file tool that performs search-and-replace operations
    on files with safety checks for path validation and content matching.

    Dependencies:
        - None standalone

    Tools:
        edit_file — search and replace content in files
    """

    PLUGIN_NAME = "edit"
    PLUGIN_ID = "edit"

    def __init__(self):
        self._allowed_paths: List[Path] = []
        self._blocked_paths: List[Path] = []

    def set_agent(self, agent: Any) -> None:
        """Receive agent reference for advanced features."""
        pass

    def configure(
        self, allowed_paths: Optional[list] = None, blocked_paths: Optional[list] = None
    ) -> None:
        """Configure path restrictions."""
        self._allowed_paths = [Path(p).expanduser().resolve() for p in (allowed_paths or [])]
        self._blocked_paths = [Path(p).expanduser().resolve() for p in (blocked_paths or [])]

    @hookimpl
    def register_tools(self) -> List[BaseTool]:
        return [EditFileTool(self)]

    @hookimpl
    def get_system_prompt(self) -> str:
        return """## File Editing

Use `edit_file` to make precise changes to existing files.

- `edit_file(path, old_string, new_string)` — Replace `old_string` with `new_string` in the file
- The `old_string` must match EXACTLY what's in the file (including whitespace)
- If there are multiple matches, use `occurrence` to pick which one (1-based, default=first)
- Use `dry_run=true` to preview changes without applying them
- Always read the file first with `read_file` to get exact content before editing
- For large rewrites, prefer `write_file` with full new content instead

IMPORTANT:
- `old_string` should be as SHORT as possible while still being unique
- Include enough surrounding context to make the match unique
- Do NOT include line numbers in `old_string` or `new_string`
"""

    def _validate_path(self, file_path: Path) -> Optional[str]:
        """Validate path against allowed/blocked lists. Returns error message or None."""
        resolved = file_path.expanduser().resolve()

        for bp in self._blocked_paths:
            if str(resolved).startswith(str(bp)):
                return f"Path is blocked: {file_path}"

        if self._allowed_paths:
            allowed = any(str(resolved).startswith(str(ap)) for ap in self._allowed_paths)
            if not allowed:
                return f"Path not in allowed list: {file_path}"

        return None


class EditFileTool(BaseTool):
    """Edit a file by replacing exact string content."""

    def __init__(self, plugin: EditFilePlugin):
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="edit_file",
            description="Replace exact content in a file. Use to make surgical edits — "
            "replace a specific string with new content. "
            "ALWAYS read the file first to get exact content before editing. "
            "The old_string must match EXACTLY (including whitespace and newlines).",
            parameters=[
                ToolParameter(
                    name="path",
                    type=ToolParameterType.STRING,
                    description="File path to edit",
                    required=True,
                ),
                ToolParameter(
                    name="old_string",
                    type=ToolParameterType.STRING,
                    description="Exact text to find and replace. Must match the file content exactly, "
                    "including whitespace, indentation, and newlines. Keep it short but unique.",
                    required=True,
                ),
                ToolParameter(
                    name="new_string",
                    type=ToolParameterType.STRING,
                    description="New text to replace old_string with",
                    required=True,
                ),
                ToolParameter(
                    name="occurrence",
                    type=ToolParameterType.INTEGER,
                    description="Which occurrence to replace (1-based). "
                    "1=first match (default), 2=second match, -1=all matches",
                    required=False,
                    default=1,
                ),
                ToolParameter(
                    name="dry_run",
                    type=ToolParameterType.BOOLEAN,
                    description="Preview changes without applying them. "
                    "Shows line numbers and diff context.",
                    required=False,
                    default=False,
                ),
            ],
        )

    async def execute(
        self,
        path: str,
        old_string: str,
        new_string: str,
        occurrence: int = 1,
        dry_run: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        try:
            file_path = Path(path).expanduser().resolve()

            path_error = self._plugin._validate_path(file_path)
            if path_error:
                return ToolResult.fail(path_error)

            if not file_path.exists():
                return ToolResult.fail(f"File not found: {path}")

            if not file_path.is_file():
                return ToolResult.fail(f"Path is not a file: {path}")

            async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                content = await f.read()

            occurrences = self._find_occurrences(content, old_string)
            total = len(occurrences)

            if total == 0:
                similar = self._find_similar(content, old_string)
                hint = f"\n\nSimilar content found:\n{similar}" if similar else ""
                return ToolResult.fail(f"String not found in {path}.{hint}")

            if dry_run:
                return self._dry_run_result(
                    file_path, content, old_string, new_string, occurrence, total
                )

            if occurrence == -1:
                new_content = content.replace(old_string, new_string)
                replaced_count = total
            else:
                if occurrence < 1 or occurrence > total:
                    return ToolResult.fail(
                        f"Occurrence {occurrence} out of range. "
                        f"Found {total} occurrence(s) in {path}."
                    )
                start, end = occurrences[occurrence - 1]
                new_content = content[:start] + new_string + content[end:]
                replaced_count = 1

            async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                await f.write(new_content)

            return ToolResult.ok(
                data={
                    "path": str(file_path.absolute()),
                    "replaced": replaced_count,
                    "total_occurrences": total,
                },
                summary=f"Replaced {replaced_count} occurrence(s) in {path} ({total} total found)",
            )

        except UnicodeDecodeError:
            return ToolResult.fail(f"Cannot edit binary file: {path}")
        except Exception as e:
            logger.warning("[EditFilePlugin] edit_file failed: %s", e)
            return ToolResult.fail(f"Error editing file: {str(e)}")

    def _find_occurrences(self, content: str, old_string: str) -> List[tuple]:
        """Find all occurrences of old_string in content. Returns list of (start, end) tuples."""
        occurrences = []
        start = 0
        while True:
            idx = content.find(old_string, start)
            if idx == -1:
                break
            occurrences.append((idx, idx + len(old_string)))
            start = idx + 1
        return occurrences

    def _find_similar(self, content: str, old_string: str, max_suggestions: int = 3) -> str:
        """Find similar content when exact match fails."""
        lines = content.split("\n")
        old_lines = old_string.split("\n")

        keywords = [line.strip() for line in old_lines if line.strip()][:5]
        if not keywords:
            return ""

        matches = []
        for i, line in enumerate(lines):
            for keyword in keywords:
                if keyword in line and len(keyword) > 4:
                    start = max(0, i - 1)
                    end = min(len(lines), i + 3)
                    context = "\n".join(f"  {j + 1}: {lines[j]}" for j in range(start, end))
                    matches.append(context)
                    break
            if len(matches) >= max_suggestions:
                break

        if matches:
            return "\n\n".join(matches[:max_suggestions])
        return ""

    def _dry_run_result(
        self,
        file_path: Path,
        content: str,
        old_string: str,
        new_string: str,
        occurrence: int,
        total: int,
    ) -> ToolResult:
        """Generate a dry run preview showing what would change."""
        lines = content.split("\n")

        occurrences = self._find_occurrences(content, old_string)
        if occurrence == -1:
            target_occurrences = occurrences
        else:
            if occurrence < 1 or occurrence > total:
                return ToolResult.fail(
                    f"Occurrence {occurrence} out of range. Found {total} occurrence(s)."
                )
            target_occurrences = [occurrences[occurrence - 1]]

        preview_lines = [f"## Dry Run Preview: {file_path.name}\n"]
        preview_lines.append(
            f"Found {total} occurrence(s), would replace {len(target_occurrences)}\n"
        )

        for idx, (start, end) in enumerate(target_occurrences, 1):
            line_num = content[:start].count("\n") + 1
            old_lines = old_string.split("\n")
            new_lines = new_string.split("\n")

            preview_lines.append(f"### Occurrence {idx} (line {line_num}):\n")
            preview_lines.append("```diff")
            for ol in old_lines:
                preview_lines.append(f"- {ol}")
            for nl in new_lines:
                preview_lines.append(f"+ {nl}")
            preview_lines.append("```\n")

        return ToolResult.ok(
            data={
                "path": str(file_path.absolute()),
                "occurrences": total,
                "would_replace": len(target_occurrences),
                "preview": "\n".join(preview_lines),
            },
            summary=f"DRY RUN: Would replace {len(target_occurrences)} occurrence(s) in {file_path.name}",
        )
