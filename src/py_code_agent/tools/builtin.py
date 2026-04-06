"""Builtin tools for file operations, bash execution, etc."""

from pathlib import Path
from typing import Any, Optional

import aiofiles

from py_code_agent.tools.base import (
    BaseTool,
    ToolDefinition,
    ToolParameter,
    ToolParameterType,
    ToolResult,
)


class ReadFileTool(BaseTool):
    """Read file tool."""

    def __init__(self, allowed_paths: Optional[list] = None, blocked_paths: Optional[list] = None):
        self.allowed_paths = [Path(p).expanduser().resolve() for p in (allowed_paths or [])]
        self.blocked_paths = [Path(p).expanduser().resolve() for p in (blocked_paths or [])]

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="read_file",
            description="Read file content with optional line range",
            parameters=[
                ToolParameter(
                    name="path",
                    type=ToolParameterType.STRING,
                    description="File path",
                    required=True
                ),
                ToolParameter(
                    name="offset",
                    type=ToolParameterType.INTEGER,
                    description="Starting line number (1-based)",
                    required=False,
                    default=1
                ),
                ToolParameter(
                    name="limit",
                    type=ToolParameterType.INTEGER,
                    description="Number of lines to read",
                    required=False,
                    default=100
                )
            ],
            examples=[
                '{"path": "/path/to/file.py"}',
                '{"path": "/path/to/file.py", "offset": 10, "limit": 20}'
            ]
        )
    
    async def execute(
        self,
        path: str,
        offset: int = 1,
        limit: int = 100
    ) -> ToolResult:
        try:
            file_path = Path(path).expanduser().resolve()
            
            if not file_path.exists():
                return ToolResult.fail(f"File not found: {path}")
            
            if self.blocked_paths:
                for bp in self.blocked_paths:
                    if str(file_path).startswith(str(bp)):
                        return ToolResult.fail(f"Path is blocked: {path}")

            if self.allowed_paths:
                allowed = any(str(file_path).startswith(str(ap)) for ap in self.allowed_paths)
                if not allowed:
                    return ToolResult.fail(f"Path not in allowed list: {path}")

            if not file_path.is_file():
                return ToolResult.fail(f"Path is not a file: {path}")
            
            async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                content = await f.read()
                lines = content.split("\n")
                
                start_idx = max(0, offset - 1)
                end_idx = min(len(lines), start_idx + limit)
                
                selected_lines = lines[start_idx:end_idx]
                
                numbered_lines = []
                for i, line in enumerate(selected_lines, start=start_idx + 1):
                    numbered_lines.append(f"{i}: {line}")
                
                result_content = "\n".join(numbered_lines)
                actual_lines = len(selected_lines)
                total_lines = len(lines)
                
                return ToolResult.ok(
                    data={
                        "content": result_content,
                        "path": str(file_path.absolute()),
                        "offset": start_idx + 1,
                        "lines_read": actual_lines,
                        "total_lines": total_lines
                    },
                    summary=f"Read {actual_lines} lines from {path} (total: {total_lines} lines)"
                )
                
        except UnicodeDecodeError:
            return ToolResult.fail(f"Cannot read binary file: {path}")
        except Exception as e:
            return ToolResult.fail(f"Error reading file: {str(e)}")


class WriteFileTool(BaseTool):
    def __init__(self, allowed_paths: Optional[list] = None, blocked_paths: Optional[list] = None):
        self.allowed_paths = [Path(p).expanduser().resolve() for p in (allowed_paths or [])]
        self.blocked_paths = [Path(p).expanduser().resolve() for p in (blocked_paths or [])]
        self._chunk_sessions: dict[str, dict] = {}

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="write_file",
            description="Write content to a file. Supports streaming: use chunk_id (1-N) and chunk_total to write large files in chunks.",
            parameters=[
                ToolParameter(
                    name="path",
                    type=ToolParameterType.STRING,
                    description="File path",
                    required=True
                ),
                ToolParameter(
                    name="content",
                    type=ToolParameterType.STRING,
                    description="File content",
                    required=True
                ),
                ToolParameter(
                    name="append",
                    type=ToolParameterType.BOOLEAN,
                    description="Append to file (not compatible with chunk_id)",
                    required=False,
                    default=False
                ),
                ToolParameter(
                    name="chunk_id",
                    type=ToolParameterType.INTEGER,
                    description="Chunk ID (1-indexed) for streaming writes. Use with chunk_total.",
                    required=False,
                    default=None
                ),
                ToolParameter(
                    name="chunk_total",
                    type=ToolParameterType.INTEGER,
                    description="Total number of chunks expected. When chunk_id == chunk_total, file is finalized.",
                    required=False,
                    default=None
                )
            ]
        )
    
    async def execute(
        self,
        path: str,
        content: str,
        append: bool = False,
        chunk_id: Optional[int] = None,
        chunk_total: Optional[int] = None
    ) -> ToolResult:
        try:
            file_path = Path(path).expanduser().resolve()

            if self.blocked_paths:
                for bp in self.blocked_paths:
                    if str(file_path).startswith(str(bp)):
                        return ToolResult.fail(f"Path is blocked: {path}")

            if self.allowed_paths:
                allowed = any(str(file_path).startswith(str(ap)) for ap in self.allowed_paths)
                if not allowed:
                    return ToolResult.fail(f"Path not in allowed list: {path}")

            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Handle chunked streaming write
            if chunk_id is not None and chunk_total is not None:
                return await self._write_chunked(file_path, content, chunk_id, chunk_total)
            
            # Regular write or append
            mode = "a" if append else "w"
            async with aiofiles.open(file_path, mode, encoding="utf-8") as f:
                await f.write(content)
            
            action = "Appended to" if append else "Wrote"
            return ToolResult.ok(
                data={"path": str(file_path.absolute()), "bytes": len(content)},
                summary=f"{action} {path} ({len(content)} bytes)"
            )
            
        except Exception as e:
            return ToolResult.fail(f"Error writing file: {str(e)}")

    async def _write_chunked(
        self,
        file_path: Path,
        content: str,
        chunk_id: int,
        chunk_total: int
    ) -> ToolResult:
        key = str(file_path.absolute())
        
        if key not in self._chunk_sessions:
            self._chunk_sessions[key] = {"chunks": [None] * chunk_total, "total": chunk_total}
        
        session = self._chunk_sessions[key]
        
        if chunk_id < 1 or chunk_id > chunk_total:
            return ToolResult.fail(f"chunk_id must be between 1 and {chunk_total}")
        
        session["chunks"][chunk_id - 1] = content
        
        filled = sum(1 for c in session["chunks"] if c is not None)
        
        if filled == chunk_total:
            final_content = "".join(session["chunks"])
            async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                await f.write(final_content)
            
            del self._chunk_sessions[key]
            
            return ToolResult.ok(
                data={"path": str(file_path.absolute()), "bytes": len(final_content), "chunks": chunk_total},
                summary=f"Wrote {file_path} ({len(final_content)} bytes from {chunk_total} chunks)"
            )
        
        return ToolResult.ok(
            data={"path": str(file_path.absolute()), "chunk": chunk_id, "total": chunk_total, "received": filled},
            summary=f"Chunk {chunk_id}/{chunk_total} received for {file_path.name} ({filled}/{chunk_total} chunks)"
        )


class ExecuteBashTool(BaseTool):
    """Execute bash command tool."""
    
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="execute_bash",
            description="Execute a bash command",
            parameters=[
                ToolParameter(
                    name="command",
                    type=ToolParameterType.STRING,
                    description="Command to execute",
                    required=True
                ),
                ToolParameter(
                    name="timeout",
                    type=ToolParameterType.INTEGER,
                    description="Timeout in seconds",
                    required=False,
                    default=30
                ),
                ToolParameter(
                    name="cwd",
                    type=ToolParameterType.STRING,
                    description="Working directory",
                    required=False
                )
            ]
        )
    
    async def execute(
        self,
        command: str,
        timeout: int = 30,
        cwd: Optional[str] = None
    ) -> ToolResult:
        import asyncio
        
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                return ToolResult.fail(f"Command timed out after {timeout} seconds")
            
            stdout_str = stdout.decode("utf-8", errors="replace")
            stderr_str = stderr.decode("utf-8", errors="replace")

            data = {
                "stdout": stdout_str,
                "stderr": stderr_str,
                "exit_code": proc.returncode,
            }

            if proc.returncode != 0:
                return ToolResult(
                    success=False,
                    error=f"Command failed with exit code {proc.returncode}\n"
                    + (f"stderr: {stderr_str}" if stderr_str else ""),
                    data=data,
                )

            return ToolResult.ok(
                data=data,
                summary=f"Command completed with exit code {proc.returncode}",
            )
            
        except Exception as e:
            return ToolResult.fail(f"Error executing command: {str(e)}")


class TaskDoneTool(BaseTool):
    def __init__(self, allowed_paths: Optional[list] = None, blocked_paths: Optional[list] = None):
        self.allowed_paths = [Path(p).expanduser().resolve() for p in (allowed_paths or [])]
        self.blocked_paths = [Path(p).expanduser().resolve() for p in (blocked_paths or [])]

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="task_done",
            description="Call this when you believe the original task is complete. Provides filesystem context for LLM to intelligently verify the output.",
            parameters=[
                ToolParameter(
                    name="original_task",
                    type=ToolParameterType.STRING,
                    description="The original user request/task to verify",
                    required=True,
                ),
                ToolParameter(
                    name="expected_output",
                    type=ToolParameterType.STRING,
                    description="Description of what the completed output should look like",
                    required=True,
                ),
                ToolParameter(
                    name="verification_context",
                    type=ToolParameterType.STRING,
                    description="Your verification reasoning - what did you create and how does it match expected output?",
                    required=False,
                ),
            ],
        )

    async def execute(
        self,
        original_task: str,
        expected_output: str,
        verification_context: str = "",
    ) -> ToolResult:
        import time

        cwd = Path.cwd()
        lines = []

        lines.append("## 🔍 VERIFICATION STEP - DO NOT SKIP")
        lines.append("")
        lines.append(f"**Task**: {original_task}")
        lines.append(f"**Expected**: {expected_output}")
        if verification_context:
            lines.append(f"**Your claim**: {verification_context}")
        lines.append("")
        lines.append("### 📋 VERIFICATION CHECKLIST (you MUST do these):")
        lines.append("")

        now = time.time()
        recent_files = []

        for allowed in self.allowed_paths:
            if allowed.exists():
                try:
                    for f in allowed.rglob("*"):
                        if f.is_file():
                            age = now - f.stat().st_mtime
                            if age < 3600:
                                recent_files.append((age, f))
                except Exception:
                    pass

        recent_files.sort(key=lambda x: x[0])

        if recent_files:
            lines.append("Recent files created/modified:")
            for age, f in recent_files[:10]:
                size = f.stat().st_size
                size_str = f"{size/1024:.1f}KB" if size > 1024 else f"{size}B"
                lines.append(f"  - `{f.name}` ({size_str})")
        else:
            lines.append("No recent files found")
        lines.append("")

        lines.append("### ⚡ YOUR ACTION REQUIRED:")
        lines.append("1. FIRST: Use `read_file` to verify each file content")
        lines.append("2. THEN: Use `execute_bash` to confirm file exists (ls -la)")
        lines.append("3. ONLY AFTER verification: Confirm completion")
        lines.append("")
        lines.append("### ⏸️ DO NOT SAY 'VERIFIED' YET!")
        lines.append("You MUST call verification tools FIRST, then respond.")
        lines.append("")

        summary = "\n".join(lines)

        return ToolResult.ok(
            data={
                "task": original_task,
                "verification_needed": True,
                "output_summary": expected_output[:500] if len(expected_output) > 500 else expected_output,
            },
            summary=summary,
        )
