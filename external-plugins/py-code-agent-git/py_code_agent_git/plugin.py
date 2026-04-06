"""Git plugin for Py Code Agent.

Provides git status, branch, and commit information tools.

Usage:
    Install: pip install py-code-agent-git
    Enable: Add 'git' to enabled plugins in config.yaml
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List

from py_code_agent.plugins.hooks import hookimpl
from py_code_agent.tools.base import BaseTool, ToolDefinition, ToolResult


class GitStatusPlugin:
    """Plugin that provides git status tool."""

    @hookimpl
    def register_tools(self) -> List[BaseTool]:
        return [GitStatusTool()]

    @hookimpl
    def get_system_prompt(self) -> str:
        return """## Git Integration

Use git tools to understand the repository context before making changes.

- `git_status`: Get current branch, recent commits, and working tree status — always run this before planning major changes."""


class GitStatusTool(BaseTool):
    """Get git status of the current repository."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="git_status",
            description="Get git status, branch, and recent commits of the current repository",
            parameters=[],
        )

    async def execute(self, **kwargs) -> ToolResult:
        try:
            cwd = Path.cwd()
            result_lines = []

            status = subprocess.run(
                ["git", "status", "--short"], cwd=cwd, capture_output=True, text=True, timeout=5
            )
            branch = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=5,
            )
            log = subprocess.run(
                ["git", "log", "--oneline", "-5"],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=5,
            )

            result_lines.append(f"Branch: {branch.stdout.strip() or '(detached)'}")
            result_lines.append(f"\nRecent commits:")
            result_lines.append(log.stdout.strip() or "No commits")
            result_lines.append(f"\nStatus ({status.returncode == 0 and 'clean' or 'dirty'}):")
            result_lines.append(status.stdout.strip() or "Not a git repository")

            return ToolResult.ok(
                data={"output": "\n".join(result_lines)},
                summary=f"Git status for {cwd.name}",
            )
        except FileNotFoundError:
            return ToolResult.fail("git not found - is git installed?")
        except subprocess.TimeoutExpired:
            return ToolResult.fail("git command timed out")
        except Exception as e:
            return ToolResult.fail(f"git error: {e}")


# Plugin entry point for pluggy
Plugin = GitStatusPlugin
