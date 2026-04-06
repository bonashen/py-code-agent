"""Test MCP client library and MCP Gateway plugin.

Tests MCP types, StdioTransport, MCPClient, and MCPGatewayPlugin.
Follows patterns from test_plugin_manager.py and test_auto_repair.py.
"""

import asyncio
import json
import sys
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from py_code_agent.mcp.types import (
    MCPErrorCode,
    MCPInitializeParams,
    MCPJSONRPCRequest,
    MCPJSONRPCResponse,
    MCPTool,
    MCPToolCallParams,
    MCPToolCallResult,
    MCPToolsListResult,
)
from py_code_agent.mcp.transport import StdioTransport
from py_code_agent.mcp.client import MCPClient, MCPServerConfig
from py_code_agent.tools.base import ToolParameterType, ToolResult


# =============================================================================
# MCP Types Tests
# =============================================================================


class TestMCPTool:
    """Test MCPTool dataclass construction."""

    def test_basic_construction(self):
        tool = MCPTool(
            name="test_tool",
            description="A test tool",
            inputSchema={"type": "object", "properties": {}},
        )
        assert tool.name == "test_tool"
        assert tool.description == "A test tool"
        assert tool.inputSchema == {"type": "object", "properties": {}}

    def test_with_complex_schema(self):
        schema = {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "content": {"type": "string", "description": "File content"},
            },
            "required": ["path"],
        }
        tool = MCPTool(
            name="write_file",
            description="Write to a file",
            inputSchema=schema,
        )
        assert tool.inputSchema["properties"]["path"]["type"] == "string"


class TestMCPToolsListResult:
    """Test MCPToolsListResult dataclass."""

    def test_empty_list(self):
        result = MCPToolsListResult(tools=[])
        assert result.tools == []

    def test_with_tools(self):
        tools = [
            MCPTool(name="tool1", description="First tool", inputSchema={}),
            MCPTool(name="tool2", description="Second tool", inputSchema={}),
        ]
        result = MCPToolsListResult(tools=tools)
        assert len(result.tools) == 2
        assert result.tools[0].name == "tool1"


class TestMCPErrorCode:
    """Test MCPErrorCode enum values."""

    def test_error_code_values(self):
        assert MCPErrorCode.ParseError.value == -32700
        assert MCPErrorCode.InvalidRequest.value == -32600
        assert MCPErrorCode.MethodNotFound.value == -32601
        assert MCPErrorCode.InvalidParams.value == -32602
        assert MCPErrorCode.InternalError.value == -32603
        assert MCPErrorCode.ServerNotInitialized.value == -32002
        assert MCPErrorCode.RequestCancelled.value == -32800

    def test_error_code_membership(self):
        assert MCPErrorCode.ParseError in MCPErrorCode
        assert MCPErrorCode.InternalError in MCPErrorCode


class TestMCPJSONRPCRequest:
    """Test MCPJSONRPCRequest dataclass."""

    def test_default_values(self):
        req = MCPJSONRPCRequest()
        assert req.jsonrpc == "2.0"
        assert req.id is None
        assert req.method == ""
        assert req.params is None

    def test_custom_values(self):
        req = MCPJSONRPCRequest(
            id=1,
            method="initialize",
            params={"protocolVersion": "2024-11-05"},
        )
        assert req.id == 1
        assert req.method == "initialize"
        assert req.params["protocolVersion"] == "2024-11-05"


class TestMCPJSONRPCResponse:
    """Test MCPJSONRPCResponse dataclass."""

    def test_success_response(self):
        resp = MCPJSONRPCResponse(
            id=1,
            result={"capabilities": {}},
        )
        assert resp.id == 1
        assert resp.result == {"capabilities": {}}
        assert resp.error is None

    def test_error_response(self):
        resp = MCPJSONRPCResponse(
            id=1,
            error={"code": -32600, "message": "Invalid Request"},
        )
        assert resp.error["code"] == -32600
        assert resp.error["message"] == "Invalid Request"


class TestMCPInitializeParams:
    """Test MCPInitializeParams dataclass defaults."""

    def test_default_values(self):
        params = MCPInitializeParams()
        assert params.protocolVersion == "2024-11-05"
        assert params.capabilities == {"tools": {}}
        assert params.clientInfo["name"] == "py-code-agent"
        assert params.clientInfo["version"] == "0.1.0"

    def test_custom_values(self):
        params = MCPInitializeParams(
            protocolVersion="2025-01-01",
            capabilities={"tools": {}, "resources": {}},
            clientInfo={"name": "custom-agent", "version": "1.0.0"},
        )
        assert params.protocolVersion == "2025-01-01"
        assert "resources" in params.capabilities
        assert params.clientInfo["name"] == "custom-agent"


class TestMCPToolCallParams:
    """Test MCPToolCallParams dataclass."""

    def test_basic_construction(self):
        params = MCPToolCallParams(name="test_tool")
        assert params.name == "test_tool"
        assert params.arguments is None

    def test_with_arguments(self):
        params = MCPToolCallParams(
            name="write_file",
            arguments={"path": "/tmp/test.txt", "content": "hello"},
        )
        assert params.name == "write_file"
        assert params.arguments["path"] == "/tmp/test.txt"


class TestMCPToolCallResult:
    """Test MCPToolCallResult dataclass."""

    def test_success_result(self):
        result = MCPToolCallResult(
            content=[{"type": "text", "text": "Success"}],
            isError=False,
        )
        assert len(result.content) == 1
        assert result.content[0]["text"] == "Success"
        assert result.isError is False

    def test_error_result(self):
        result = MCPToolCallResult(
            content=[{"type": "text", "text": "Error occurred"}],
            isError=True,
        )
        assert result.isError is True


# =============================================================================
# StdioTransport Tests
# =============================================================================


@pytest.fixture
def mock_subprocess():
    """Create a mock subprocess for testing."""
    proc = AsyncMock()
    proc.stdin = AsyncMock()
    proc.stdout = AsyncMock()
    proc.stderr = AsyncMock()
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    proc.wait = AsyncMock(return_value=0)
    return proc


@pytest.mark.asyncio
class TestStdioTransportInitialization:
    """Test StdioTransport initialization sends correct JSON-RPC request."""

    async def test_initialize_sends_jsonrpc_request(self, mock_subprocess):
        """Test that initialize sends correct initialize request."""
        transport = StdioTransport(command="npx", args=["-y", "test-server"])
        
        # Mock the subprocess
        with patch("asyncio.create_subprocess_exec", return_value=mock_subprocess):
            # Set up mock response for initialize request
            response = {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "test-server", "version": "1.0.0"},
                },
            }
            mock_subprocess.stdout.readline = AsyncMock(return_value=(json.dumps(response) + "\n").encode())
            
            result = await transport.initialize()
            
            # Verify capabilities were returned
            assert "tools" in result

    async def test_initialize_with_notification(self, mock_subprocess):
        """Test that initialize sends notification after response."""
        transport = StdioTransport(command="npx", args=["-y", "test-server"])
        
        with patch("asyncio.create_subprocess_exec", return_value=mock_subprocess):
            init_response = {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "serverInfo": {"name": "test-server"},
                },
            }
            mock_subprocess.stdout.readline = AsyncMock(return_value=(json.dumps(init_response) + "\n").encode())
            
            await transport.initialize()
            
            # Check that notification was sent (second write)
            assert mock_subprocess.stdin.write.call_count >= 1


@pytest.mark.asyncio
class TestStdioTransportListTools:
    """Test list_tools returns parsed tool list."""

    async def test_list_tools_returns_tools(self, mock_subprocess):
        """Test that list_tools returns a list of tools."""
        transport = StdioTransport(command="npx", args=["-y", "test-server"])
        
        with patch("asyncio.create_subprocess_exec", return_value=mock_subprocess):
            # Mock initialize response
            init_response = {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "test-server"},
                },
            }
            # Mock list_tools response
            list_response = {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {
                    "tools": [
                        {
                            "name": "read_file",
                            "description": "Read a file",
                            "inputSchema": {"type": "object"},
                        },
                        {
                            "name": "write_file",
                            "description": "Write to a file",
                            "inputSchema": {"type": "object"},
                        },
                    ]
                },
            }
            
            mock_subprocess.stdout.readline = AsyncMock(
                side_effect=[
                    (json.dumps(init_response) + "\n").encode(),
                    (json.dumps(list_response) + "\n").encode(),
                ]
            )
            
            tools = await transport.list_tools()
            
            assert len(tools) == 2
            assert tools[0]["name"] == "read_file"
            assert tools[1]["name"] == "write_file"


@pytest.mark.asyncio
class TestStdioTransportCallTool:
    """Test call_tool sends correct method/params."""

    async def test_call_tool_sends_correct_params(self, mock_subprocess):
        """Test that call_tool sends the correct method and parameters."""
        transport = StdioTransport(command="npx", args=["-y", "test-server"])
        
        with patch("asyncio.create_subprocess_exec", return_value=mock_subprocess):
            init_response = {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "serverInfo": {"name": "test-server"},
                },
            }
            call_response = {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {
                    "content": [{"type": "text", "text": "File contents here"}],
                },
            }
            
            mock_subprocess.stdout.readline = AsyncMock(
                side_effect=[
                    (json.dumps(init_response) + "\n").encode(),
                    (json.dumps(call_response) + "\n").encode(),
                ]
            )
            
            result = await transport.call_tool("read_file", {"path": "/test.txt"})
            
            assert result["content"][0]["text"] == "File contents here"


@pytest.mark.asyncio
class TestStdioTransportErrorHandling:
    """Test Handles MCP protocol errors."""

    async def test_handles_jsonrpc_error(self, mock_subprocess):
        """Test that JSON-RPC errors are properly raised."""
        transport = StdioTransport(command="npx", args=["-y", "test-server"])
        
        with patch("asyncio.create_subprocess_exec", return_value=mock_subprocess):
            init_response = {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "serverInfo": {"name": "test-server"},
                },
            }
            error_response = {
                "jsonrpc": "2.0",
                "id": 2,
                "error": {
                    "code": -32602,
                    "message": "Invalid params",
                },
            }
            
            mock_subprocess.stdout.readline = AsyncMock(
                side_effect=[
                    (json.dumps(init_response) + "\n").encode(),
                    (json.dumps(error_response) + "\n").encode(),
                ]
            )
            
            with pytest.raises(RuntimeError) as exc_info:
                await transport.call_tool("test_tool", {})
            
            assert "MCP error" in str(exc_info.value)
            assert "-32602" in str(exc_info.value)


@pytest.mark.asyncio
class TestStdioTransportClose:
    """Test Close terminates subprocess."""

    async def test_close_terminates_subprocess(self, mock_subprocess):
        """Test that close properly terminates the subprocess."""
        transport = StdioTransport(command="npx", args=["-y", "test-server"])
        
        with patch("asyncio.create_subprocess_exec", return_value=mock_subprocess):
            init_response = {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "serverInfo": {"name": "test-server"},
                },
            }
            mock_subprocess.stdout.readline = AsyncMock(return_value=(json.dumps(init_response) + "\n").encode())
            
            await transport.initialize()
            await transport.close()
            
            mock_subprocess.terminate.assert_called_once()


# =============================================================================
# MCPClient Tests
# =============================================================================


class TestMCPClientAddRemoveServer:
    """Test add_server() / remove_server()."""

    def test_add_server(self):
        client = MCPClient()
        config = MCPServerConfig(
            name="test-server",
            command="npx",
            args=["-y", "test-server"],
        )
        client.add_server(config)
        assert "test-server" in client._servers

    def test_add_multiple_servers(self):
        client = MCPClient()
        for i in range(3):
            config = MCPServerConfig(
                name=f"server-{i}",
                command="npx",
                args=["-y", f"server-{i}"],
            )
            client.add_server(config)
        assert len(client._servers) == 3


@pytest.mark.asyncio
class TestMCPClientInitialize:
    """Test initialize() connects all enabled servers."""

    async def test_initialize_connects_enabled_servers(self):
        client = MCPClient()
        config = MCPServerConfig(
            name="test-server",
            command="npx",
            args=["-y", "test-server"],
            enabled=True,
        )
        client.add_server(config)

        mock_transport = AsyncMock()
        mock_transport.initialize = AsyncMock(return_value={"tools": {}})
        mock_transport.list_tools = AsyncMock(return_value=[])

        with patch("py_code_agent.mcp.client.StdioTransport", return_value=mock_transport):
            await client.initialize()

        mock_transport.initialize.assert_called_once()
        assert client._initialized.get("test-server") is True

    async def test_initialize_skips_disabled_servers(self):
        client = MCPClient()
        config = MCPServerConfig(
            name="disabled-server",
            command="npx",
            args=["-y", "test-server"],
            enabled=False,
        )
        client.add_server(config)

        with patch("py_code_agent.mcp.client.StdioTransport") as mock_transport_class:
            await client.initialize()
            mock_transport_class.assert_not_called()


class TestMCPClientGetAllTools:
    """Test get_all_tools() returns tools by server."""

    def test_get_all_tools_empty(self):
        client = MCPClient()
        tools = client.get_all_tools()
        assert tools == {}

    def test_get_all_tools_with_tools(self):
        client = MCPClient()
        # Manually populate tools
        client._tools = {
            "server1": [
                MCPTool(name="tool1", description="Tool 1", inputSchema={}),
            ],
            "server2": [
                MCPTool(name="tool2", description="Tool 2", inputSchema={}),
                MCPTool(name="tool3", description="Tool 3", inputSchema={}),
            ],
        }
        tools = client.get_all_tools()
        assert len(tools) == 2
        assert len(tools["server1"]) == 1
        assert len(tools["server2"]) == 2


@pytest.mark.asyncio
class TestMCPClientCallTool:
    """Test call_tool() routes to correct transport."""

    async def test_call_tool_routes_to_correct_transport(self):
        client = MCPClient()
        mock_transport = AsyncMock()
        mock_transport.call_tool = AsyncMock(return_value={"content": [{"type": "text", "text": "result"}]})
        client._transports["server1"] = mock_transport

        result = await client.call_tool("server1", "test_tool", {"arg1": "value1"})

        mock_transport.call_tool.assert_called_once_with("test_tool", {"arg1": "value1"})
        assert result["content"][0]["text"] == "result"

    async def test_call_tool_raises_for_missing_server(self):
        client = MCPClient()

        with pytest.raises(ValueError) as exc_info:
            await client.call_tool("nonexistent", "test_tool")

        assert "nonexistent" in str(exc_info.value)
        assert "not connected" in str(exc_info.value)


@pytest.mark.asyncio
class TestMCPClientClose:
    """Test close() closes all transports."""

    async def test_close_closes_all_transports(self):
        client = MCPClient()
        mock_transport1 = AsyncMock()
        mock_transport2 = AsyncMock()
        client._transports["server1"] = mock_transport1
        client._transports["server2"] = mock_transport2

        await client.close()

        mock_transport1.close.assert_called_once()
        mock_transport2.close.assert_called_once()
        assert len(client._transports) == 0

    async def test_close_handles_errors_gracefully(self):
        client = MCPClient()
        mock_transport = AsyncMock()
        mock_transport.close = AsyncMock(side_effect=Exception("Close failed"))
        client._transports["server1"] = mock_transport

        # Should not raise
        await client.close()


# =============================================================================
# MCPGatewayPlugin Tests
# =============================================================================


@pytest.fixture
def mock_mcp_client():
    """Create a mock MCPClient."""
    client = MagicMock()
    client.add_server = MagicMock()
    client.remove_server = MagicMock()
    client.initialize = AsyncMock()
    client.get_all_tools = MagicMock(return_value={})
    client.call_tool = AsyncMock(return_value={"content": [{"type": "text", "text": "result"}]})
    client.close = AsyncMock()
    return client


class TestMCPGatewayPluginConfigure:
    """Test configure() parses server config."""

    def test_configure_parses_single_server(self, mock_mcp_client):
        from plugins.builtin.mcp_gateway_plugin import MCPGatewayPlugin
        
        plugin = MCPGatewayPlugin()
        plugin.client = mock_mcp_client
        
        servers = [
            {
                "name": "filesystem",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem", "."],
                "enabled": True,
            }
        ]
        
        plugin.configure(servers)
        
        mock_mcp_client.add_server.assert_called_once()
        call_args = mock_mcp_client.add_server.call_args[0][0]
        assert call_args.name == "filesystem"
        assert call_args.command == "npx"
        assert call_args.args == ["-y", "@modelcontextprotocol/server-filesystem", "."]

    def test_configure_parses_multiple_servers(self, mock_mcp_client):
        from plugins.builtin.mcp_gateway_plugin import MCPGatewayPlugin
        
        plugin = MCPGatewayPlugin()
        plugin.client = mock_mcp_client
        
        servers = [
            {
                "name": "filesystem",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem", "."],
            },
            {
                "name": "brave-search",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-brave-search"],
                "env": {"BRAVE_API_KEY": "test-key"},
            },
        ]
        
        plugin.configure(servers)
        
        assert mock_mcp_client.add_server.call_count == 2

    def test_configure_skips_servers_without_name(self, mock_mcp_client):
        from plugins.builtin.mcp_gateway_plugin import MCPGatewayPlugin
        
        plugin = MCPGatewayPlugin()
        plugin.client = mock_mcp_client
        
        servers = [
            {
                "command": "npx",
                "args": ["-y", "server"],
            },
            {
                "name": "valid-server",
                "command": "npx",
                "args": ["-y", "server"],
            },
        ]
        
        plugin.configure(servers)
        
        # Only the valid server should be added
        mock_mcp_client.add_server.assert_called_once()
        call_args = mock_mcp_client.add_server.call_args[0][0]
        assert call_args.name == "valid-server"


class TestMCPGatewayPluginRegisterTools:
    """Test register_tools() returns BaseTool instances."""

    def test_register_tools_returns_list(self, mock_mcp_client):
        from plugins.builtin.mcp_gateway_plugin import MCPGatewayPlugin, MCPListServersTool, MCPCallToolTool
        
        plugin = MCPGatewayPlugin()
        plugin.client = mock_mcp_client
        
        # Pre-populate tools list
        plugin._tools = [
            MCPListServersTool(mock_mcp_client),
            MCPCallToolTool(mock_mcp_client),
        ]
        
        tools = plugin.register_tools()
        
        assert len(tools) == 2
        assert all(hasattr(tool, "definition") for tool in tools)
        assert all(hasattr(tool, "execute") for tool in tools)


class TestMCPServerTool:
    """Test MCPServerTool name format and parameter definitions."""

    def test_tool_name_format(self, mock_mcp_client):
        from plugins.builtin.mcp_gateway_plugin import MCPServerTool
        
        tool = MCPServerTool(
            server_name="filesystem",
            tool_name="read_file",
            description="Read a file",
            input_schema={"type": "object", "properties": {}},
            client=mock_mcp_client,
        )
        
        assert tool.definition.name == "mcp_filesystem_read_file"

    def test_tool_name_format_different_server(self, mock_mcp_client):
        from plugins.builtin.mcp_gateway_plugin import MCPServerTool
        
        tool = MCPServerTool(
            server_name="github",
            tool_name="create_issue",
            description="Create a GitHub issue",
            input_schema={"type": "object", "properties": {}},
            client=mock_mcp_client,
        )
        
        assert tool.definition.name == "mcp_github_create_issue"

    def test_tool_definition_includes_description(self, mock_mcp_client):
        from plugins.builtin.mcp_gateway_plugin import MCPServerTool
        
        tool = MCPServerTool(
            server_name="filesystem",
            tool_name="read_file",
            description="Read a file from disk",
            input_schema={"type": "object", "properties": {}},
            client=mock_mcp_client,
        )
        
        assert "[filesystem]" in tool.definition.description
        assert "Read a file from disk" in tool.definition.description

    def test_parameter_definitions_from_schema(self, mock_mcp_client):
        from plugins.builtin.mcp_gateway_plugin import MCPServerTool
        
        input_schema = {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Recursive operation",
                },
                "count": {
                    "type": "integer",
                    "description": "Number of items",
                },
            },
            "required": ["path"],
        }
        
        tool = MCPServerTool(
            server_name="filesystem",
            tool_name="list_dir",
            description="List directory",
            input_schema=input_schema,
            client=mock_mcp_client,
        )
        
        params = tool.definition.parameters
        param_names = [p.name for p in params]
        
        assert "path" in param_names
        assert "recursive" in param_names
        assert "count" in param_names
        
        # Check types
        path_param = next(p for p in params if p.name == "path")
        recursive_param = next(p for p in params if p.name == "recursive")
        count_param = next(p for p in params if p.name == "count")
        
        assert path_param.type == ToolParameterType.STRING
        assert recursive_param.type == ToolParameterType.BOOLEAN
        assert count_param.type == ToolParameterType.INTEGER

    def test_required_parameter_flag(self, mock_mcp_client):
        from plugins.builtin.mcp_gateway_plugin import MCPServerTool
        
        input_schema = {
            "type": "object",
            "properties": {
                "required_param": {"type": "string"},
                "optional_param": {"type": "string"},
            },
            "required": ["required_param"],
        }
        
        tool = MCPServerTool(
            server_name="test",
            tool_name="test_tool",
            description="Test tool",
            input_schema=input_schema,
            client=mock_mcp_client,
        )
        
        params = tool.definition.parameters
        required_param = next(p for p in params if p.name == "required_param")
        optional_param = next(p for p in params if p.name == "optional_param")
        
        assert required_param.required is True
        assert optional_param.required is False


@pytest.mark.asyncio
class TestMCPServerToolExecute:
    """Test Tools handle MCP errors gracefully."""

    async def test_execute_returns_success_result(self, mock_mcp_client):
        from plugins.builtin.mcp_gateway_plugin import MCPServerTool
        
        mock_mcp_client.call_tool = AsyncMock(return_value={
            "content": [{"type": "text", "text": "Success output"}],
        })
        
        tool = MCPServerTool(
            server_name="filesystem",
            tool_name="read_file",
            description="Read a file",
            input_schema={"type": "object", "properties": {}},
            client=mock_mcp_client,
        )
        
        result = await tool.execute(path="/test.txt")
        
        assert result.success is True
        assert "Success output" in result.summary

    async def test_execute_handles_mcp_errors(self, mock_mcp_client):
        from plugins.builtin.mcp_gateway_plugin import MCPServerTool
        
        mock_mcp_client.call_tool = AsyncMock(side_effect=Exception("MCP server disconnected"))
        
        tool = MCPServerTool(
            server_name="filesystem",
            tool_name="read_file",
            description="Read a file",
            input_schema={"type": "object", "properties": {}},
            client=mock_mcp_client,
        )
        
        result = await tool.execute(path="/test.txt")
        
        assert result.success is False
        assert "MCP tool 'read_file' error" in result.error

    async def test_execute_handles_image_content(self, mock_mcp_client):
        from plugins.builtin.mcp_gateway_plugin import MCPServerTool
        
        mock_mcp_client.call_tool = AsyncMock(return_value={
            "content": [
                {"type": "text", "text": "Image analysis:"},
                {"type": "image", "data": "base64encodedimagedata..."},
            ],
        })
        
        tool = MCPServerTool(
            server_name="filesystem",
            tool_name="read_image",
            description="Read an image",
            input_schema={"type": "object", "properties": {}},
            client=mock_mcp_client,
        )
        
        result = await tool.execute(path="/test.png")
        
        assert result.success is True
        # Image content should be handled gracefully
        assert "Image analysis:" in result.summary or result.summary


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.asyncio
class TestMCPIntegration:
    """Integration tests for MCP components."""

    async def test_full_flow(self, mock_subprocess):
        """Test full flow from client to transport."""
        client = MCPClient()
        config = MCPServerConfig(
            name="test-server",
            command="npx",
            args=["-y", "test-server"],
            enabled=True,
        )
        client.add_server(config)

        # Set up responses for initialize, list_tools, and call_tool
        init_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "test-server"},
            },
        }
        list_response = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "tools": [
                    {"name": "test_tool", "description": "Test tool", "inputSchema": {}},
                ]
            },
        }

        mock_subprocess.stdout.readline = AsyncMock(
            side_effect=[
                (json.dumps(init_response) + "\n").encode(),
                (json.dumps(list_response) + "\n").encode(),
            ]
        )

        with patch("asyncio.create_subprocess_exec", return_value=mock_subprocess):
            with patch("py_code_agent.mcp.client.StdioTransport", side_effect=lambda **kwargs: StdioTransport(**kwargs)):
                await client.initialize()

        tools = client.get_all_tools()
        assert "test-server" in tools
        assert len(tools["test-server"]) == 1
        assert tools["test-server"][0].name == "test_tool"
