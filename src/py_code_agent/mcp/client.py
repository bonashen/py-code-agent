"""MCP client — manages multiple server connections."""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from .types import MCPTool
from .transport import MCPTransport, StdioTransport

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
                logger.info("[MCP] Server '%s' initialized — %d tools", name, len(self._tools[name]))
            except Exception as e:
                logger.warning("[MCP] Failed to initialize server '%s': %s", name, e)
                self._initialized[name] = False

    def get_all_tools(self) -> Dict[str, List[MCPTool]]:
        return dict(self._tools)

    def get_tools_for_server(self, server_name: str) -> List[MCPTool]:
        return self._tools.get(server_name, [])

    async def call_tool(self, server_name: str, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
