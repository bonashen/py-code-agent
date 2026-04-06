"""Test A2A Gateway plugin — implements the A2A v0.3.0 protocol.

This tests:
- AgentCard construction and serialization
- A2AMessage parsing and serialization
- A2AClient peer management and HTTP calls
- A2AServer endpoints and authentication
- A2AGatewayPlugin lifecycle and tools
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

# Ensure the plugin is importable
_plugin_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_plugin_root / "plugins" / "builtin"))
sys.path.insert(0, str(_plugin_root))

from a2a_gateway_plugin import (
    AgentCard,
    A2AClient,
    A2AGatewayPlugin,
    A2AGetMyCardTool,
    A2AListPeersTool,
    A2AMessage,
    A2ASendMessageTool,
    A2AServer,
    _substitute_env_vars,
)


# =============================================================================
# AgentCard Tests
# =============================================================================


class TestAgentCard:
    """Test AgentCard dataclass construction and serialization."""

    def test_construction_with_all_fields(self):
        """AgentCard construction with all fields."""
        card = AgentCard(
            name="TestAgent",
            description="A test agent",
            url="http://localhost:18800/a2a/jsonrpc",
            version="0.3.0",
            skills=[{"id": "coding", "name": "coding", "description": "Code generation"}],
            capabilities={"streaming": True, "async": True},
            authentication={"type": "bearer", "required": True},
        )
        assert card.name == "TestAgent"
        assert card.description == "A test agent"
        assert card.url == "http://localhost:18800/a2a/jsonrpc"
        assert card.version == "0.3.0"
        assert len(card.skills) == 1
        assert card.skills[0]["id"] == "coding"
        assert card.capabilities["streaming"] is True
        assert card.authentication["type"] == "bearer"

    def test_to_dict_serialization(self):
        """to_dict() serialization."""
        card = AgentCard(
            name="TestAgent",
            description="A test agent",
            url="http://localhost:18800/a2a/jsonrpc",
            skills=[{"id": "coding"}],
            capabilities={"streaming": True},
        )
        result = card.to_dict()
        assert isinstance(result, dict)
        assert result["name"] == "TestAgent"
        assert result["description"] == "A test agent"
        assert result["url"] == "http://localhost:18800/a2a/jsonrpc"
        assert result["version"] == "0.3.0"
        assert result["skills"] == [{"id": "coding"}]
        assert result["capabilities"] == {"streaming": True}

    def test_default_values(self):
        """Default values."""
        card = AgentCard(
            name="TestAgent",
            description="A test agent",
            url="http://localhost:18800/a2a/jsonrpc",
        )
        assert card.version == "0.3.0"
        assert card.skills == []
        assert card.capabilities == {"streaming": True}
        assert card.authentication is None

    def test_skills_and_capabilities_fields(self):
        """skills and capabilities fields."""
        card = AgentCard(
            name="TestAgent",
            description="A test agent",
            url="http://localhost:18800/a2a/jsonrpc",
            skills=[
                {"id": "coding", "name": "coding"},
                {"id": "testing", "name": "testing"},
            ],
            capabilities={"streaming": True, "async": True, "sse": True},
        )
        assert len(card.skills) == 2
        assert card.skills[0]["id"] == "coding"
        assert card.skills[1]["id"] == "testing"
        assert card.capabilities["sse"] is True


# =============================================================================
# A2AMessage Tests
# =============================================================================


class TestA2AMessage:
    """Test A2AMessage dataclass parsing and serialization."""

    def test_construction_with_text_parts(self):
        """Construction with text parts."""
        msg = A2AMessage(
            role="user",
            parts=[{"kind": "text", "text": "Hello!"}],
            agent_id="agent-123",
        )
        assert msg.role == "user"
        assert len(msg.parts) == 1
        assert msg.parts[0]["text"] == "Hello!"
        assert msg.agent_id == "agent-123"

    def test_from_dict_parsing(self):
        """from_dict() parsing."""
        data = {
            "role": "agent",
            "parts": [{"kind": "text", "text": "Hello!"}],
            "agentId": "agent-123",
            "parentId": "parent-456",
            "metadata": {"key": "value"},
        }
        msg = A2AMessage.from_dict(data)
        assert msg.role == "agent"
        assert len(msg.parts) == 1
        assert msg.agent_id == "agent-123"
        assert msg.parent_id == "parent-456"
        assert msg.metadata == {"key": "value"}

    def test_to_dict_serialization(self):
        """to_dict() serialization."""
        msg = A2AMessage(
            role="user",
            parts=[{"kind": "text", "text": "Hello!"}],
            agent_id="agent-123",
            parent_id="parent-456",
            metadata={"key": "value"},
        )
        result = msg.to_dict()
        assert result["role"] == "user"
        assert result["parts"] == [{"kind": "text", "text": "Hello!"}]
        assert result["agentId"] == "agent-123"
        assert result["parentId"] == "parent-456"
        assert result["metadata"] == {"key": "value"}

    def test_get_text_extraction(self):
        """get_text() extraction."""
        msg = A2AMessage(
            role="agent",
            parts=[
                {"kind": "text", "text": "Hello"},
                {"kind": "text", "text": "World"},
                {"kind": "image", "url": "http://example.com/img.png"},
            ],
        )
        text = msg.get_text()
        assert "Hello" in text
        assert "World" in text
        assert "http://example.com/img.png" not in text

    def test_empty_fallback_handling(self):
        """Empty/fallback handling."""
        msg = A2AMessage(role="user", parts=[])
        assert msg.get_text() == ""

        msg_default = A2AMessage.from_dict({})
        assert msg_default.role == "user"
        assert msg_default.parts == []
        assert msg_default.metadata == {}


# =============================================================================
# A2AClient Tests
# =============================================================================


class TestA2AClient:
    """Test A2AClient peer management and HTTP calls."""

    def test_add_peer(self):
        """add_peer() adds a peer agent."""
        client = A2AClient()
        client.add_peer(
            name="BackendBot",
            agent_card_url="http://backend:18800/.well-known/agent-card.json",
            token="secret123",
        )
        assert "BackendBot" in client._peers
        assert client._peers["BackendBot"]["url"] == "http://backend:18800/.well-known/agent-card.json"
        assert client._peers["BackendBot"]["token"] == "secret123"

    def test_remove_peer(self):
        """remove_peer() removes a peer agent."""
        client = A2AClient()
        client.add_peer(
            name="BackendBot",
            agent_card_url="http://backend:18800/.well-known/agent-card.json",
        )
        result = client.remove_peer("BackendBot")
        assert result is True
        assert "BackendBot" not in client._peers

    def test_remove_peer_nonexistent(self):
        """remove_peer() returns False for non-existent peer."""
        client = A2AClient()
        result = client.remove_peer("NonExistent")
        assert result is False

    def test_list_peers(self):
        """list_peers() returns all configured peers."""
        client = A2AClient()
        client.add_peer(
            name="BackendBot",
            agent_card_url="http://backend:18800/.well-known/agent-card.json",
            token="secret123",
        )
        client.add_peer(
            name="FrontendBot",
            agent_card_url="http://frontend:18800/.well-known/agent-card.json",
        )
        peers = client.list_peers()
        assert len(peers) == 2
        assert "BackendBot" in peers
        assert "FrontendBot" in peers
        assert peers["BackendBot"]["has_token"] is True
        assert peers["FrontendBot"]["has_token"] is False

    @pytest.mark.asyncio
    async def test_fetch_agent_card_mocked_http_response(self):
        """fetch_agent_card() parses mocked HTTP response."""
        client = A2AClient()
        client.add_peer(
            name="TestAgent",
            agent_card_url="http://test:18800/.well-known/agent-card.json",
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "name": "TestAgent",
            "description": "A test agent",
            "url": "http://test:18800/a2a/jsonrpc",
            "version": "0.3.0",
            "skills": [{"id": "coding"}],
            "capabilities": {"streaming": True},
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            card = await client.fetch_agent_card("TestAgent")

        assert card is not None
        assert card.name == "TestAgent"
        assert card.description == "A test agent"
        assert card.url == "http://test:18800/a2a/jsonrpc"

    @pytest.mark.asyncio
    async def test_fetch_agent_card_missing_peer(self):
        """fetch_agent_card() handles missing peers."""
        client = A2AClient()
        card = await client.fetch_agent_card("NonExistent")
        assert card is None

    @pytest.mark.asyncio
    async def test_send_message_mocked_http_post(self):
        """send_message() constructs correct JSON-RPC payload."""
        client = A2AClient()
        client.add_peer(
            name="TestAgent",
            agent_card_url="http://test:18800/.well-known/agent-card.json",
            token="secret123",
        )

        # Pre-set agent card to avoid HTTP fetch
        client._agent_cards["TestAgent"] = AgentCard(
            name="TestAgent",
            description="Test",
            url="http://test:18800/a2a/jsonrpc",
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "result": {
                "message": {
                    "role": "agent",
                    "parts": [{"kind": "text", "text": "Hello back!"}],
                }
            },
            "id": 1,
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await client.send_message(
                peer_name="TestAgent",
                message="Hello!",
                agent_id="agent-123",
            )

        assert result["jsonrpc"] == "2.0"
        assert "result" in result
        assert result["result"]["message"]["parts"][0]["text"] == "Hello back!"

    def test_send_message_missing_peer(self):
        """send_message() handles missing peers."""
        client = A2AClient()

        async def run_test():
            with pytest.raises(ValueError) as exc_info:
                await client.send_message(peer_name="NonExistent", message="Hello!")
            assert "NonExistent" in str(exc_info.value)
            assert "not configured" in str(exc_info.value)

        import asyncio
        asyncio.run(run_test())

    @pytest.mark.asyncio
    async def test_send_message_http_error(self):
        """send_message() handles HTTP errors gracefully."""
        client = A2AClient()
        client.add_peer(
            name="TestAgent",
            agent_card_url="http://test:18800/.well-known/agent-card.json",
        )

        # Pre-set agent card
        client._agent_cards["TestAgent"] = AgentCard(
            name="TestAgent",
            description="Test",
            url="http://test:18800/a2a/jsonrpc",
        )

        # Create a proper async mock client that raises an HTTP error
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        
        # Create an HTTP error with proper request/response
        request = httpx.Request("POST", "http://test:18800/a2a/jsonrpc")
        response = httpx.Response(500, text="Server Error", request=request)
        http_error = httpx.HTTPStatusError("Server error", request=request, response=response)
        
        mock_client.post = AsyncMock(side_effect=http_error)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError) as exc_info:
                await client.send_message(peer_name="TestAgent", message="Hello!")
            assert exc_info.value.response.status_code == 500

    @pytest.mark.asyncio
    async def test_bearer_token_in_authorization_header(self):
        """Bearer token is included in Authorization header."""
        client = A2AClient()
        client.add_peer(
            name="TestAgent",
            agent_card_url="http://test:18800/.well-known/agent-card.json",
            token="my-secret-token",
        )

        # Pre-set agent card
        client._agent_cards["TestAgent"] = AgentCard(
            name="TestAgent",
            description="Test",
            url="http://test:18800/a2a/jsonrpc",
        )

        captured_headers = {}

        mock_response = MagicMock()
        mock_response.json.return_value = {"jsonrpc": "2.0", "result": {}, "id": 1}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        
        async def capture_post(*args, **kwargs):
            captured_headers.update(kwargs.get("headers", {}))
            return mock_response
        
        mock_client.post = capture_post

        with patch("httpx.AsyncClient", return_value=mock_client):
            await client.send_message(peer_name="TestAgent", message="Hello!")

        assert "Authorization" in captured_headers
        assert captured_headers["Authorization"] == "Bearer my-secret-token"


# =============================================================================
# A2AServer Tests
# =============================================================================


class TestA2AServer:
    """Test A2AServer endpoints and authentication."""

    @pytest.fixture
    def agent_card(self):
        """Create a test agent card."""
        return AgentCard(
            name="TestAgent",
            description="A test agent",
            url="http://localhost:18800/a2a/jsonrpc",
            skills=[{"id": "coding"}],
        )

    @pytest.fixture
    def mock_handler(self):
        """Create a mock message handler."""
        async def handler(text: str) -> str:
            return f"Echo: {text}"
        return handler

    @pytest.fixture
    def server(self, agent_card, mock_handler):
        """Create an A2AServer instance."""
        return A2AServer(
            host="127.0.0.1",
            port=18800,
            token="test-token",
            agent_card=agent_card,
            message_handler=mock_handler,
        )

    @pytest.fixture
    def fastapi_app(self, server):
        """Create a FastAPI app for testing."""
        # Manually build the app like start() does
        from fastapi import FastAPI, HTTPException, Request

        app = FastAPI(title="A2A Gateway", version="0.3.0")

        @app.get("/.well-known/agent-card.json")
        async def get_agent_card():
            """Return the agent card."""
            return server.agent_card.to_dict()

        @app.get("/health")
        async def health_check():
            """Health check endpoint."""
            return {"status": "ok", "agent": server.agent_card.name}

        @app.post("/a2a/jsonrpc")
        async def handle_jsonrpc(request: Request):
            """Handle JSON-RPC requests."""
            # Check authentication
            if server.token:
                auth = request.headers.get("Authorization", "")
                if not auth.startswith("Bearer ") or auth[7:] != server.token:
                    raise HTTPException(status_code=401, detail="Unauthorized")

            body = await request.json()
            method = body.get("method", "")
            request_id = body.get("id")

            if method == "message/send":
                return await server._handle_message_send(body, request_id)
            elif method == "message/subscribe":
                return await server._handle_message_subscribe(body, request_id)
            else:
                raise HTTPException(
                    status_code=404, detail=f"Method '{method}' not supported"
                )

        return app

    def test_agent_card_endpoint_returns_correct_json(self, fastapi_app, agent_card):
        """Agent card endpoint returns correct JSON."""
        client = TestClient(fastapi_app)
        response = client.get("/.well-known/agent-card.json")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == agent_card.name
        assert data["description"] == agent_card.description
        assert data["url"] == agent_card.url
        assert data["version"] == "0.3.0"

    def test_health_endpoint(self, fastapi_app, agent_card):
        """Health check endpoint."""
        client = TestClient(fastapi_app)
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["agent"] == agent_card.name

    def test_jsonrpc_endpoint_handles_message_send(self, fastapi_app):
        """JSON-RPC endpoint handles message/send."""
        client = TestClient(fastapi_app)
        payload = {
            "jsonrpc": "2.0",
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": "Hello!"}],
                }
            },
            "id": 1,
        }
        response = client.post(
            "/a2a/jsonrpc",
            json=payload,
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert "result" in data
        assert data["id"] == 1

    def test_bearer_auth_rejects_invalid_tokens(self, fastapi_app):
        """Bearer auth rejects invalid tokens."""
        client = TestClient(fastapi_app)
        payload = {
            "jsonrpc": "2.0",
            "method": "message/send",
            "params": {"message": {"role": "user", "parts": []}},
            "id": 1,
        }
        response = client.post(
            "/a2a/jsonrpc",
            json=payload,
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert response.status_code == 401

    def test_bearer_auth_rejects_missing_tokens(self, fastapi_app):
        """Bearer auth rejects missing tokens."""
        client = TestClient(fastapi_app)
        payload = {
            "jsonrpc": "2.0",
            "method": "message/send",
            "params": {"message": {"role": "user", "parts": []}},
            "id": 1,
        }
        response = client.post("/a2a/jsonrpc", json=payload)
        assert response.status_code == 401

    def test_bearer_auth_allows_valid_tokens(self, fastapi_app):
        """Bearer auth allows valid tokens."""
        client = TestClient(fastapi_app)
        payload = {
            "jsonrpc": "2.0",
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": "Hello!"}],
                }
            },
            "id": 1,
        }
        response = client.post(
            "/a2a/jsonrpc",
            json=payload,
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code == 200

    def test_unsupported_methods_return_404(self, fastapi_app):
        """Unsupported methods return 404."""
        client = TestClient(fastapi_app)
        payload = {
            "jsonrpc": "2.0",
            "method": "unknown/method",
            "params": {},
            "id": 1,
        }
        response = client.post(
            "/a2a/jsonrpc",
            json=payload,
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code == 404


# =============================================================================
# A2AGatewayPlugin Tests
# =============================================================================


class TestA2AGatewayPlugin:
    """Test A2AGatewayPlugin lifecycle and tools."""

    @pytest.fixture
    def plugin(self):
        """Create an A2AGatewayPlugin instance."""
        return A2AGatewayPlugin()

    def test_configure_sets_all_fields(self, plugin):
        """configure() sets all fields."""
        plugin.configure(
            port=18800,
            host="127.0.0.1",
            token="test-token",
            name="MyAgent",
            description="My custom agent",
            skills=[{"id": "coding", "name": "coding"}],
            peers=[{"name": "BackendBot", "url": "http://backend:18800/.well-known/agent-card.json"}],
        )
        assert plugin._config["port"] == 18800
        assert plugin._config["host"] == "127.0.0.1"
        assert plugin._config["token"] == "test-token"
        assert plugin._config["name"] == "MyAgent"
        assert plugin._config["description"] == "My custom agent"
        assert len(plugin._config["skills"]) == 1
        assert len(plugin._config["peers"]) == 1

    def test_env_var_substitution_in_config(self, plugin, monkeypatch):
        """Env var substitution in config (${VAR})."""
        monkeypatch.setenv("A2A_TOKEN", "env-token-123")

        plugin.configure(
            token="${A2A_TOKEN}",
            peers=[
                {
                    "name": "BackendBot",
                    "agentCardUrl": "http://backend:18800/.well-known/agent-card.json",
                }
            ],
        )
        assert plugin._config["token"] == "env-token-123"
        # Peer URL is substituted in on_agent_start(), not configure()
        assert plugin._config["peers"][0]["agentCardUrl"] == "http://backend:18800/.well-known/agent-card.json"

    @pytest.mark.asyncio
    async def test_on_agent_start_initializes_server_and_peers(self, plugin, monkeypatch):
        """on_agent_start() initializes server and peers."""
        monkeypatch.setenv("PEER_URL", "http://backend:18800/.well-known/agent-card.json")

        plugin.configure(
            port=18800,
            host="127.0.0.1",
            token="test-token",
            name="TestAgent",
            peers=[
                {
                    "name": "BackendBot",
                    "agentCardUrl": "${PEER_URL}",
                }
            ],
        )

        # Mock the server start to avoid actual server startup
        mock_server = MagicMock()
        mock_server.start = AsyncMock()
        mock_server.is_running = True

        # Patch the module that was loaded into sys.modules
        with patch.object(plugin, "server", None):
            with patch("a2a_gateway_plugin.A2AServer", return_value=mock_server):
                plugin.on_agent_start("test input")
                await asyncio.sleep(0.1)

        # Check that peer was added
        assert "BackendBot" in plugin.client.list_peers()

    @pytest.mark.asyncio
    async def test_on_agent_end_stops_server(self, plugin):
        """on_agent_end() stops the server."""
        mock_server = MagicMock()
        mock_server.stop = AsyncMock()
        mock_server.is_running = False

        plugin.server = mock_server

        # Mock asyncio.get_event_loop to avoid loop issues
        mock_loop = MagicMock()
        mock_loop.is_running.return_value = True

        with patch("asyncio.get_event_loop", return_value=mock_loop):
            with patch("asyncio.create_task") as mock_create:
                mock_create.return_value = MagicMock()
                plugin.on_agent_end()
                # Verify server.stop was called via create_task
                mock_create.assert_called_once()

    def test_register_tools_returns_base_tool_instances(self, plugin):
        """register_tools() returns BaseTool instances."""
        # Create a mock server
        mock_server = MagicMock()
        mock_server.agent_card = MagicMock()
        plugin.server = mock_server

        tools = plugin.register_tools()

        assert isinstance(tools, list)
        assert len(tools) >= 3

        # Check each tool is a BaseTool
        from py_code_agent.tools.base import BaseTool

        for tool in tools:
            assert isinstance(tool, BaseTool)

        # Check tool names
        tool_names = [tool.definition.name for tool in tools]
        assert "a2a_list_peers" in tool_names
        assert "a2a_send_message" in tool_names
        assert "a2a_get_my_card" in tool_names

    @pytest.mark.asyncio
    async def test_tools_handle_errors_gracefully(self, plugin):
        """Tools handle errors gracefully."""
        plugin.server = None  # Simulate uninitialized server

        # Create tool without server
        tool = A2AGetMyCardTool(None)

        result = await tool.execute()

        assert result.success is False
        assert "not initialized" in result.error.lower()

    def test_tool_definitions(self, plugin):
        """Tool definitions are correct."""
        mock_server = MagicMock()
        mock_server.agent_card = MagicMock()
        plugin.server = mock_server

        tools = plugin.register_tools()

        # Find each tool and check its definition
        for tool in tools:
            if tool.definition.name == "a2a_list_peers":
                assert "peer" in tool.definition.description.lower()
                assert len(tool.definition.parameters) == 0
            elif tool.definition.name == "a2a_send_message":
                assert "send" in tool.definition.description.lower()
                params = {p.name: p for p in tool.definition.parameters}
                assert "peer_name" in params
                assert "message" in params
            elif tool.definition.name == "a2a_get_my_card":
                assert "card" in tool.definition.description.lower()


# =============================================================================
# Environment Variable Substitution Tests
# =============================================================================


class TestSubstituteEnvVars:
    """Test environment variable substitution."""

    def test_substitutes_single_var(self, monkeypatch):
        """Substitutes a single ${VAR}."""
        monkeypatch.setenv("TEST_VAR", "test_value")
        result = _substitute_env_vars("Value is: ${TEST_VAR}")
        assert result == "Value is: test_value"

    def test_substitutes_multiple_vars(self, monkeypatch):
        """Substitutes multiple ${VAR} patterns."""
        monkeypatch.setenv("VAR1", "first")
        monkeypatch.setenv("VAR2", "second")
        result = _substitute_env_vars("${VAR1} and ${VAR2}")
        assert result == "first and second"

    def test_leaves_unset_vars_empty(self, monkeypatch):
        """Leaves unset ${VAR} as empty string."""
        monkeypatch.delenv("UNSET_VAR", raising=False)
        result = _substitute_env_vars("Value: ${UNSET_VAR}")
        assert result == "Value: "

    def test_handles_nested_dicts(self, monkeypatch):
        """Handles nested dictionaries."""
        monkeypatch.setenv("SECRET", "my-secret")
        result = _substitute_env_vars({
            "token": "${SECRET}",
            "nested": {
                "key": "${SECRET}",
            },
        })
        assert result["token"] == "my-secret"
        assert result["nested"]["key"] == "my-secret"

    def test_handles_lists(self, monkeypatch):
        """Handles lists."""
        monkeypatch.setenv("ITEM", "value")
        result = _substitute_env_vars(["${ITEM}", "static", {"key": "${ITEM}"}])
        assert result[0] == "value"
        assert result[1] == "static"
        assert result[2]["key"] == "value"

    def test_leaves_non_strings_unchanged(self):
        """Leaves non-string values unchanged."""
        result = _substitute_env_vars(42)
        assert result == 42
        result = _substitute_env_vars(True)
        assert result is True


# =============================================================================
# Individual Tool Tests
# =============================================================================


class TestA2AListPeersTool:
    """Test A2AListPeersTool."""

    @pytest.fixture
    def client(self):
        """Create a client with some peers."""
        client = A2AClient()
        client.add_peer(
            name="BackendBot",
            agent_card_url="http://backend:18800/.well-known/agent-card.json",
            token="secret123",
        )
        client.add_peer(
            name="FrontendBot",
            agent_card_url="http://frontend:18800/.well-known/agent-card.json",
        )
        return client

    @pytest.fixture
    def tool(self, client):
        """Create the tool."""
        return A2AListPeersTool(client)

    def test_definition(self, tool):
        """Tool definition is correct."""
        assert tool.definition.name == "a2a_list_peers"
        assert "peer" in tool.definition.description.lower()
        assert len(tool.definition.parameters) == 0

    @pytest.mark.asyncio
    async def test_execute(self, tool):
        """Execute returns peer list."""
        result = await tool.execute()
        assert result.success is True
        assert "peers" in result.data
        assert len(result.data["peers"]) == 2
        assert "BackendBot" in result.data["peers"]
        assert "FrontendBot" in result.data["peers"]
        assert result.data["peers"]["BackendBot"]["has_token"] is True


class TestA2ASendMessageTool:
    """Test A2ASendMessageTool."""

    @pytest.fixture
    def client(self):
        """Create a client."""
        return A2AClient()

    @pytest.fixture
    def tool(self, client):
        """Create the tool."""
        return A2ASendMessageTool(client)

    def test_definition(self, tool):
        """Tool definition is correct."""
        assert tool.definition.name == "a2a_send_message"
        assert "send" in tool.definition.description.lower()
        params = {p.name: p for p in tool.definition.parameters}
        assert "peer_name" in params
        assert "message" in params
        assert "agent_id" in params
        assert params["peer_name"].required is True
        assert params["message"].required is True
        assert params["agent_id"].required is False

    @pytest.mark.asyncio
    async def test_execute_success(self, tool, monkeypatch):
        """Execute sends message successfully."""
        # Add peer
        tool._client.add_peer(
            name="TestPeer",
            agent_card_url="http://test:18800/.well-known/agent-card.json",
        )

        # Pre-set agent card
        tool._client._agent_cards["TestPeer"] = AgentCard(
            name="TestPeer",
            description="Test",
            url="http://test:18800/a2a/jsonrpc",
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "result": {
                "message": {
                    "role": "agent",
                    "parts": [{"kind": "text", "text": "Hello back!"}],
                }
            },
            "id": 1,
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tool.execute(peer_name="TestPeer", message="Hello!")

        assert result.success is True
        assert "response" in result.data
        assert result.data["response_text"] == "Hello back!"
        assert "TestPeer" in result.summary

    @pytest.mark.asyncio
    async def test_execute_missing_peer(self, tool):
        """Execute handles missing peer."""
        result = await tool.execute(peer_name="NonExistent", message="Hello!")
        assert result.success is False
        assert "not configured" in result.error.lower() or "configuration error" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_http_error(self, tool):
        """Execute handles HTTP errors gracefully."""
        # Add peer
        tool._client.add_peer(
            name="TestPeer",
            agent_card_url="http://test:18800/.well-known/agent-card.json",
        )

        # Pre-set agent card
        tool._client._agent_cards["TestPeer"] = AgentCard(
            name="TestPeer",
            description="Test",
            url="http://test:18800/a2a/jsonrpc",
        )

        # Create proper HTTP error
        request = httpx.Request("POST", "http://test:18800/a2a/jsonrpc")
        response = httpx.Response(500, text="Server Error", request=request)
        http_error = httpx.HTTPStatusError("Server error", request=request, response=response)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=http_error)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tool.execute(peer_name="TestPeer", message="Hello!")

        assert result.success is False
        assert "failed to send message" in result.error.lower() or "500" in result.error


class TestA2AGetMyCardTool:
    """Test A2AGetMyCardTool."""

    @pytest.fixture
    def mock_server(self):
        """Create a mock server."""
        server = MagicMock()
        server.agent_card = AgentCard(
            name="TestAgent",
            description="A test agent",
            url="http://localhost:18800/a2a/jsonrpc",
            skills=[{"id": "coding"}],
            capabilities={"streaming": True},
        )
        return server

    def test_definition(self, mock_server):
        """Tool definition is correct."""
        tool = A2AGetMyCardTool(mock_server)
        assert tool.definition.name == "a2a_get_my_card"
        assert "card" in tool.definition.description.lower()
        assert len(tool.definition.parameters) == 0

    @pytest.mark.asyncio
    async def test_execute_with_server(self, mock_server):
        """Execute returns agent card when server exists."""
        tool = A2AGetMyCardTool(mock_server)
        result = await tool.execute()
        assert result.success is True
        assert result.data["name"] == "TestAgent"
        assert result.data["url"] == "http://localhost:18800/a2a/jsonrpc"
        assert "TestAgent" in result.summary

    @pytest.mark.asyncio
    async def test_execute_without_server(self):
        """Execute returns error when server is None."""
        tool = A2AGetMyCardTool(None)
        result = await tool.execute()
        assert result.success is False
        assert "not initialized" in result.error.lower()


# =============================================================================
# A2AGatewayPlugin Integration Tests
# =============================================================================


class TestA2AGatewayPluginIntegration:
    """Integration tests for A2AGatewayPlugin."""

    @pytest.fixture
    def plugin(self):
        """Create a configured plugin."""
        plugin = A2AGatewayPlugin()
        plugin.configure(
            port=18800,
            host="127.0.0.1",
            token="test-token",
            name="TestAgent",
            description="A test agent",
            skills=[{"id": "coding", "name": "coding"}],
            peers=[
                {
                    "name": "BackendBot",
                    "agentCardUrl": "http://backend:18800/.well-known/agent-card.json",
                    "token": "backend-token",
                }
            ],
        )
        return plugin

    def test_full_lifecycle(self, plugin, monkeypatch):
        """Test full lifecycle: configure -> on_agent_start -> on_agent_end."""
        import asyncio

        # Mock server creation and startup
        mock_server = MagicMock()
        mock_server.start = AsyncMock()
        mock_server.stop = AsyncMock()

        with patch("plugins.builtin.a2a_gateway_plugin.A2AServer", return_value=mock_server):
            # on_agent_start
            plugin.on_agent_start("test input")

            # Give async tasks time to run
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(asyncio.sleep(0.1))

            # Check server was created and started
            assert plugin.server is not None

            # Check peer was added
            peers = plugin.client.list_peers()
            assert "BackendBot" in peers

            # on_agent_end
            with patch("asyncio.get_event_loop") as mock_get_loop:
                mock_loop = MagicMock()
                mock_loop.is_running.return_value = True
                mock_get_loop.return_value = mock_loop
                plugin.on_agent_end()

    def test_handle_inbound_message_with_agent(self, plugin):
        """Test _handle_inbound_message with agent reference."""
        import asyncio

        # Create a mock agent
        mock_agent = MagicMock()

        # Create an async generator for run()
        async def mock_run(input_text):
            # Yield a mock event
            mock_event = MagicMock()
            mock_event.data = {"type": "content", "content": f"Response to: {input_text}"}
            yield mock_event

        mock_agent.run = mock_run
        plugin.set_agent(mock_agent)

        # Test the handler
        async def test_handler():
            response = await plugin._handle_inbound_message("Hello!")
            return response

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        response = loop.run_until_complete(test_handler())

        assert "Response to: Hello!" in response

    def test_handle_inbound_message_without_agent(self, plugin):
        """Test _handle_inbound_message without agent reference."""
        import asyncio

        # Ensure no agent is set
        plugin._agent_ref = None

        async def test_handler():
            response = await plugin._handle_inbound_message("Hello!")
            return response

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        response = loop.run_until_complete(test_handler())

        assert "not initialized" in response.lower()


# =============================================================================
# Import/Dependency Tests
# =============================================================================


def test_plugin_imports():
    """Test that all plugin components can be imported."""
    # These should all be importable from the plugin module
    assert AgentCard is not None
    assert A2AMessage is not None
    assert A2AClient is not None
    assert A2AServer is not None
    assert A2AGatewayPlugin is not None
    assert A2AListPeersTool is not None
    assert A2ASendMessageTool is not None
    assert A2AGetMyCardTool is not None
    assert _substitute_env_vars is not None
