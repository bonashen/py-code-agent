"""MCP transport abstraction — stdio and HTTP+SSE."""

import asyncio
import json
import logging
import shutil
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class MCPTransport(ABC):
    @abstractmethod
    async def initialize(self) -> Dict[str, Any]:
        """Send initialize request, return server capabilities."""
        pass

    @abstractmethod
    async def list_tools(self) -> List[Dict[str, Any]]:
        """List available tools."""
        pass

    @abstractmethod
    async def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Call a tool by name."""
        pass

    @abstractmethod
    async def close(self) -> None:
        pass


class StdioTransport(MCPTransport):
    """MCP transport over stdin/stdout using a subprocess."""

    def __init__(
        self,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        timeout: float = 30.0,
    ):
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.timeout = timeout
        self._process: Optional[asyncio.subprocess.Process] = None
        self._request_id = 0
        self._lock = asyncio.Lock()
        self._initialized = False
        self._capabilities: Dict[str, Any] = {}
        self._stderr_lines: List[str] = []

    def _build_env(self) -> Dict[str, str]:
        import os
        env = dict(os.environ)
        env.update(self.env)
        return env

    async def initialize(self) -> Dict[str, Any]:
        import os
        cmd = shutil.which(self.command) or self.command
        self._process = await asyncio.create_subprocess_exec(
            cmd,
            *(self.args or []),
            env=self._build_env(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        from .types import MCPInitializeParams
        params = MCPInitializeParams()
        result = await self._send_request("initialize", params.__dict__)
        self._capabilities = result.get("capabilities", {})
        await self._send_notification("initialized", {"protocolVersion": result.get("protocolVersion", "2024-11-05")})
        self._initialized = True
        return self._capabilities

    async def list_tools(self) -> List[Dict[str, Any]]:
        if not self._initialized:
            await self.initialize()
        result = await self._send_request("tools/list", {})
        return result.get("tools", [])

    async def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self._initialized:
            await self.initialize()
        return await self._send_request("tools/call", {"name": name, "arguments": arguments or {}})

    async def _send_request(self, method: str, params: Any) -> Any:
        async with self._lock:
            self._request_id += 1
            req_id = self._request_id
            request = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
            line = json.dumps(request, separators=(",", ":")) + "\n"
            logger.debug("[MCP stdio] --> %s", line[:200])
            proc_stdin = self._process.stdin
            proc_stdout = self._process.stdout
            proc_stderr = self._process.stderr
            if proc_stdin is None or proc_stdout is None:
                raise RuntimeError("MCP subprocess streams unavailable")
            proc_stdin.write(line.encode())
            await proc_stdin.drain()
            response_line = await asyncio.wait_for(proc_stdout.readline(), timeout=self.timeout)
            if not response_line:
                err_bytes = await proc_stderr.read() if proc_stderr else b""
                raise RuntimeError(f"MCP server closed stdin. stderr: {err_bytes.decode()[:500]}")
            response = json.loads(response_line.decode())
            logger.debug("[MCP stdio] <-- %s", response_line.decode()[:200])
            if "error" in response:
                raise RuntimeError(f"MCP error: {response['error']}")
            return response.get("result", {})

    async def _send_notification(self, method: str, params: Any) -> None:
        async with self._lock:
            if self._process is None or self._process.stdin is None:
                return
            notification = {"jsonrpc": "2.0", "method": method, "params": params}
            line = json.dumps(notification, separators=(",", ":")) + "\n"
            self._process.stdin.write(line.encode())
            await self._process.stdin.drain()

    async def close(self) -> None:
        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
            self._process = None
