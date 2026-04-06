"""MCP protocol types — JSON-RPC 2.0 + MCP spec."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Union
from enum import Enum


@dataclass
class MCPTool:
    name: str
    description: str
    inputSchema: Dict[str, Any]


@dataclass
class MCPToolsListResult:
    tools: List[MCPTool]


class MCPErrorCode(Enum):
    ParseError = -32700
    InvalidRequest = -32600
    MethodNotFound = -32601
    InvalidParams = -32602
    InternalError = -32603
    ServerNotInitialized = -32002
    RequestCancelled = -32800


@dataclass
class MCPJSONRPCRequest:
    jsonrpc: Literal["2.0"] = "2.0"
    id: Union[int, str, None] = None
    method: str = ""
    params: Optional[Dict[str, Any]] = None


@dataclass
class MCPJSONRPCResponse:
    jsonrpc: Literal["2.0"] = "2.0"
    id: Union[int, str, None] = None
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None


@dataclass
class MCPInitializeParams:
    protocolVersion: str = "2024-11-05"
    capabilities: Dict[str, Any] = field(default_factory=lambda: {"tools": {}})
    clientInfo: Dict[str, str] = field(default_factory=lambda: {"name": "py-code-agent", "version": "0.1.0"})


@dataclass
class MCPToolCallParams:
    name: str
    arguments: Optional[Dict[str, Any]] = None


@dataclass
class MCPToolCallResult:
    content: List[Dict[str, Any]]
    isError: bool = False


@dataclass
class MCPResource:
    uri: str
    name: str
    description: Optional[str] = None
    mimeType: Optional[str] = None


@dataclass
class MCPPrompt:
    name: str
    description: Optional[str] = None
    arguments: Optional[List[Dict[str, str]]] = None
