from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from py_code_agent.plugins.hooks import hookimpl
from py_code_agent.tools.base import (
    BaseTool,
    ToolDefinition,
    ToolParameter,
    ToolParameterType,
    ToolResult,
)

logger = logging.getLogger(__name__)


@dataclass
class MCPServerConfig:
    name: str
    command: str
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    transport: Literal["stdio", "http"] = "stdio"
    url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    enabled: bool = True


@dataclass
class MCPTool:
    name: str
    description: str
    inputSchema: Dict[str, Any]


class MCPTransport(ABC):
    @abstractmethod
    async def initialize(self) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def list_tools(self) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    async def call_tool(
        self, name: str, arguments: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass


class StdioTransport(MCPTransport):
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
        params = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "clientInfo": {"name": "py-code-agent-mcp-gateway", "version": "0.1.0"},
        }
        result = await self._send_request("initialize", params)
        self._capabilities = result.get("capabilities", {})
        await self._send_notification(
            "initialized", {"protocolVersion": result.get("protocolVersion", "2024-11-05")}
        )
        self._initialized = True
        return self._capabilities

    async def list_tools(self) -> List[Dict[str, Any]]:
        if not self._initialized:
            await self.initialize()
        result = await self._send_request("tools/list", {})
        return result.get("tools", [])

    async def call_tool(
        self, name: str, arguments: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        if not self._initialized:
            await self.initialize()
        return await self._send_request("tools/call", {"name": name, "arguments": arguments or {}})

    async def _send_request(self, method: str, params: Any) -> Any:
        async with self._lock:
            self._request_id += 1
            req_id = self._request_id
            request = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
            line = json.dumps(request, separators=(",", ":")) + "\n"
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


class MCPClient:
    def __init__(self):
        self._servers: Dict[str, MCPServerConfig] = {}
        self._transports: Dict[str, MCPTransport] = {}
        self._tools: Dict[str, List[MCPTool]] = {}
        self._initialized: Dict[str, bool] = {}

    def add_server(self, config: MCPServerConfig) -> None:
        self._servers[config.name] = config

    def remove_server(self, name: str) -> None:
        if name in self._transports:
            asyncio.create_task(self._transports[name].close())
            del self._transports[name]
        self._servers.pop(name, None)
        self._tools.pop(name, None)
        self._initialized.pop(name, None)

    async def initialize(self) -> None:
        for name, config in self._servers.items():
            if not config.enabled:
                continue
            if name in self._initialized and self._initialized[name]:
                continue
            try:
                transport: MCPTransport
                if config.transport == "stdio":
                    transport = StdioTransport(
                        command=config.command,
                        args=config.args,
                        env=config.env,
                    )
                else:
                    raise NotImplementedError("HTTP transport not yet implemented")
                self._transports[name] = transport
                caps = await transport.initialize()
                tools = await transport.list_tools()
                self._tools[name] = [
                    MCPTool(
                        name=t["name"],
                        description=t.get("description", ""),
                        inputSchema=t.get("inputSchema", {}),
                    )
                    for t in tools
                ]
                self._initialized[name] = True
                logger.info(
                    "[MCP] Server '%s' initialized — %d tools", name, len(self._tools[name])
                )
            except Exception as e:
                logger.warning("[MCP] Failed to initialize server '%s': %s", name, e)
                self._initialized[name] = False

    def get_all_tools(self) -> Dict[str, List[MCPTool]]:
        return dict(self._tools)

    def get_tools_for_server(self, server_name: str) -> List[MCPTool]:
        return self._tools.get(server_name, [])

    async def call_tool(
        self, server_name: str, tool_name: str, arguments: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        transport = self._transports.get(server_name)
        if not transport:
            raise ValueError(f"MCP server '{server_name}' not connected")
        return await transport.call_tool(tool_name, arguments)

    async def close(self) -> None:
        for name, transport in list(self._transports.items()):
            try:
                await asyncio.wait_for(transport.close(), timeout=5.0)
            except Exception as e:
                logger.warning("[MCP] Error closing server '%s': %s", name, e)
        self._transports.clear()
        self._initialized.clear()


class MCPServerTool(BaseTool):
    def __init__(
        self,
        server_name: str,
        tool_name: str,
        description: str,
        input_schema: Dict[str, Any],
        client: MCPClient,
    ):
        self.server_name = server_name
        self.tool_name = tool_name
        self.description = description
        self.input_schema = input_schema
        self.client = client
        self._def = self._build_definition()

    def _build_definition(self) -> ToolDefinition:
        params = []
        properties = self.input_schema.get("properties", {})
        required = self.input_schema.get("required", [])
        for param_name, param_spec in properties.items():
            param_type_str = param_spec.get("type", "string")
            type_map = {
                "string": ToolParameterType.STRING,
                "integer": ToolParameterType.INTEGER,
                "number": ToolParameterType.NUMBER,
                "boolean": ToolParameterType.BOOLEAN,
                "array": ToolParameterType.ARRAY,
                "object": ToolParameterType.OBJECT,
            }
            params.append(
                ToolParameter(
                    name=param_name,
                    type=type_map.get(param_type_str, ToolParameterType.STRING),
                    description=param_spec.get("description", ""),
                    required=param_name in required,
                )
            )
        return ToolDefinition(
            name=f"mcp_{self.server_name}_{self.tool_name}",
            description=f"[{self.server_name}] {self.description}",
            parameters=params,
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._def

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            result = await self.client.call_tool(self.server_name, self.tool_name, kwargs)
            content = result.get("content", [])
            if isinstance(content, list):
                text_parts = []
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            text_parts.append(item.get("text", ""))
                        elif item.get("type") == "image":
                            text_parts.append(f"[image: {item.get('data', '')[:50]}...]")
                        else:
                            text_parts.append(str(item))
                    else:
                        text_parts.append(str(item))
                text = "\n".join(text_parts)
            else:
                text = str(content)
            return ToolResult.ok(
                data=result,
                summary=text[:200] if text else "MCP tool executed",
            )
        except Exception as e:
            logger.warning("[MCP Gateway] Tool '%s' failed: %s", self.tool_name, e)
            return ToolResult.fail(f"MCP tool '{self.tool_name}' error: {e}")


class MCPListServersTool(BaseTool):
    def __init__(self, client: MCPClient):
        self.client = client

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mcp_list_servers",
            description="List all connected MCP servers and their available tools.",
            parameters=[],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        tools_by_server = self.client.get_all_tools()
        if not tools_by_server:
            return ToolResult.ok(data={"servers": [], "message": "No MCP servers connected"})
        lines = []
        for server, tools in tools_by_server.items():
            lines.append(f"## {server} ({len(tools)} tools)")
            for t in tools:
                lines.append(f"  - `{t.name}`: {t.description[:80]}")
        return ToolResult.ok(
            data={"servers": tools_by_server},
            summary=f"{len(tools_by_server)} servers, {sum(len(v) for v in tools_by_server.values())} tools",
        )


class MCPCallToolTool(BaseTool):
    def __init__(self, client: MCPClient):
        self.client = client

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mcp_call_tool",
            description="Call a specific MCP tool on a connected server.",
            parameters=[
                ToolParameter(
                    name="server_name",
                    type=ToolParameterType.STRING,
                    description="MCP server name",
                    required=True,
                ),
                ToolParameter(
                    name="tool_name",
                    type=ToolParameterType.STRING,
                    description="Tool name to call",
                    required=True,
                ),
            ],
        )

    async def execute(self, server_name: str, tool_name: str, **kwargs: Any) -> ToolResult:
        try:
            result = await self.client.call_tool(server_name, tool_name, kwargs)
            content = result.get("content", [])
            if isinstance(content, list):
                text_parts = [
                    item.get("text", str(item)) for item in content if isinstance(item, dict)
                ]
                text = "\n".join(text_parts)
            else:
                text = str(content)
            return ToolResult.ok(
                data=result,
                summary=text[:200] if text else "Tool executed",
            )
        except Exception as e:
            return ToolResult.fail(f"MCP call failed: {e}")


class MCPGatewayPlugin:
    def __init__(self):
        self.client = MCPClient()
        self._servers: Dict[str, MCPServerConfig] = {}
        self._tools: List[BaseTool] = []
        self._config: Dict[str, Any] = {}

    def configure(self, servers: List[Dict[str, Any]]) -> None:
        self._config = {"servers": servers}
        for cfg in servers:
            name = cfg.get("name", "")
            if not name:
                continue
            mcpcfg = MCPServerConfig(
                name=name,
                command=cfg.get("command", ""),
                args=cfg.get("args", []),
                env=cfg.get("env", {}),
                transport=cfg.get("transport", "stdio"),
                url=cfg.get("url"),
                headers=cfg.get("headers"),
                enabled=cfg.get("enabled", True),
            )
            self.client.add_server(mcpcfg)
            self._servers[name] = mcpcfg

    @hookimpl
    def register_tools(self) -> List[BaseTool]:
        base_tools = [
            MCPListServersTool(self.client),
            MCPCallToolTool(self.client),
        ]
        return base_tools + self._tools

    @hookimpl
    def on_agent_start(self, input: str) -> None:
        for cfg in self._config.get("servers", []):
            name = cfg.get("name", "")
            env = cfg.get("env", {})
            for k, v in env.items():
                if isinstance(v, str) and v.startswith("${") and v.endswith("}"):
                    env[k] = os.environ.get(v[2:-1], "")

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._initialize_async())
            else:
                loop.run_until_complete(self._initialize_async())
        except RuntimeError:
            asyncio.run(self._initialize_async())

    async def _initialize_async(self) -> None:
        await self.client.initialize()

        tools = []
        for server_name, tools_list in self.client.get_all_tools().items():
            for tool in tools_list:
                tools.append(
                    MCPServerTool(
                        server_name,
                        tool.name,
                        tool.description,
                        tool.inputSchema,
                        self.client,
                    )
                )
        self._tools = tools
        logger.info(
            "[MCP Gateway] Initialized — %d servers, %d tools",
            len(self._servers),
            len(self._tools),
        )

    @hookimpl
    def on_agent_end(self) -> None:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.client.close())
            else:
                loop.run_until_complete(self.client.close())
        except RuntimeError:
            asyncio.run(self.client.close())

    @hookimpl
    def get_system_prompt(self) -> str:
        lines = [
            "## MCP Servers (Model Context Protocol)",
            "",
            "MCP servers extend the agent with tools from external services.",
        ]
        if self._tools:
            by_server: dict = {}
            for t in self._tools:
                by_server.setdefault(t.server_name, []).append(t)
            for server, tools in by_server.items():
                lines.append(f"- **{server}** ({len(tools)} tools)")
                for t in tools[:5]:
                    lines.append(f"  - `{t.definition.name}`: {t.definition.description[:80]}")
                if len(tools) > 5:
                    lines.append(f"  ... and {len(tools) - 5} more")
            lines.append("")
            lines.append("Use `mcp_call_tool(server_name, tool_name, ...)` to call an MCP tool.")
        else:
            lines.append("No MCP servers are currently connected.")
            lines.append("Configure servers in `config.yaml` under `plugins.gateway.mcp.servers`.")
        return "\n".join(lines)


Plugin = MCPGatewayPlugin
