"""A2A Gateway plugin for Py Code Agent.

Enables agent-to-agent communication via A2A (Agent-to-Agent) v0.3.0 protocol.

This plugin provides:
- Exposes HTTP endpoints for A2A protocol (.well-known/agent-card.json, /a2a/jsonrpc)
- Receives inbound messages from peer agents
- Sends messages to peer agents
- Streaming responses via SSE

Dependencies:
    - (file:gateway) for MCP Gateway plugin integration

Usage:
    Install: pip install py-code-agent-a2a-gateway
    Enable: Add 'a2a_gateway' to enabled plugins in config.yaml
    Configure: Set host, port, token, name, description in config
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import httpx

from py_code_agent.plugins.hooks import hookimpl
from py_code_agent.tools.base import (
    BaseTool,
    ToolDefinition,
    ToolParameter,
    ToolParameterType,
    ToolResult,
)


# =============================================================================
# A2A Types
# =============================================================================


@dataclass
class AgentCard:
    """A2A Agent Card — describes this agent's capabilities."""

    name: str
    description: str
    url: str  # JSON-RPC endpoint
    version: str = "0.3.0"
    skills: List[Dict[str, str]] = field(default_factory=list)
    capabilities: Dict[str, Any] = field(default_factory=lambda: {"streaming": True})
    authentication: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "version": self.version,
            "skills": self.skills,
            "capabilities": self.capabilities,
        }
        if self.authentication:
            result["authentication"] = self.authentication
        return result


@dataclass
class A2AMessage:
    """A2A message structure."""

    role: str  # "user" or "agent"
    parts: List[Dict[str, Any]]
    agent_id: Optional[str] = None
    parent_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> A2AMessage:
        """Create message from dictionary."""
        return cls(
            role=data.get("role", "user"),
            parts=data.get("parts", []),
            agent_id=data.get("agentId"),
            parent_id=data.get("parentId"),
            metadata=data.get("metadata", {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result: Dict[str, Any] = {
            "role": self.role,
            "parts": self.parts,
        }
        if self.agent_id:
            result["agentId"] = self.agent_id
        if self.parent_id:
            result["parentId"] = self.parent_id
        if self.metadata:
            result["metadata"] = self.metadata
        return result

    def get_text(self) -> str:
        """Extract text content from message parts."""
        texts = []
        for part in self.parts:
            if part.get("kind") == "text" and "text" in part:
                texts.append(part["text"])
        return " ".join(texts)


# =============================================================================
# Utility Functions
# =============================================================================


def _substitute_env_vars(value: Any) -> Any:
    """Substitute environment variables in strings.

    Supports ${VAR} syntax.
    """
    if isinstance(value, str):
        pattern = re.compile(r"\$\{([^}]+)\}")

        def replacer(match: re.Match) -> str:
            var_name = match.group(1)
            return os.environ.get(var_name, "")

        return pattern.sub(replacer, value)
    elif isinstance(value, dict):
        return {k: _substitute_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_substitute_env_vars(item) for item in value]
    return value


# =============================================================================
# A2A JSON-RPC Client (for outbound calls)
# =============================================================================


class A2AClient:
    """A2A JSON-RPC client for calling peer agents."""

    def __init__(self):
        self._peers: Dict[str, Dict[str, Any]] = {}
        self._agent_cards: Dict[str, AgentCard] = {}

    def add_peer(
        self,
        name: str,
        agent_card_url: str,
        token: Optional[str] = None,
    ) -> None:
        """Add a peer agent.

        Args:
            name: Short name for the peer
            agent_card_url: URL to the peer's agent-card.json
            token: Optional bearer token for authentication
        """
        self._peers[name] = {
            "url": agent_card_url,
            "token": token,
        }

    def remove_peer(self, name: str) -> bool:
        """Remove a peer agent."""
        if name in self._peers:
            del self._peers[name]
            if name in self._agent_cards:
                del self._agent_cards[name]
            return True
        return False

    def list_peers(self) -> Dict[str, Dict[str, Any]]:
        """List all configured peers."""
        return {
            name: {
                "url": info["url"],
                "has_token": info["token"] is not None,
            }
            for name, info in self._peers.items()
        }

    async def fetch_agent_card(self, peer_name: str) -> Optional[AgentCard]:
        """Fetch and parse the agent card for a peer."""
        peer = self._peers.get(peer_name)
        if not peer:
            return None

        # Check cache
        if peer_name in self._agent_cards:
            return self._agent_cards[peer_name]

        # Fetch from URL
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(peer["url"])
                resp.raise_for_status()
                data = resp.json()

            card = AgentCard(
                name=data.get("name", "Unknown"),
                description=data.get("description", ""),
                url=data.get("url", ""),
                version=data.get("version", "0.3.0"),
                skills=data.get("skills", []),
                capabilities=data.get("capabilities", {"streaming": True}),
                authentication=data.get("authentication"),
            )
            self._agent_cards[peer_name] = card
            return card
        except Exception:
            return None

    async def send_message(
        self,
        peer_name: str,
        message: str,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a message to a peer agent.

        Args:
            peer_name: Name of the peer (configured via add_peer)
            message: Message text to send
            agent_id: Optional agent ID for routing

        Returns:
            JSON-RPC response from the peer
        """
        peer = self._peers.get(peer_name)
        if not peer:
            raise ValueError(f"A2A peer '{peer_name}' not configured")

        # Fetch agent card to get endpoint URL
        card = await self.fetch_agent_card(peer_name)
        if card and card.url:
            endpoint = card.url
        else:
            # Fallback: construct from agent card URL
            endpoint = peer["url"].replace("/.well-known/agent-card.json", "/a2a/jsonrpc")

        payload = {
            "jsonrpc": "2.0",
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": message}],
                }
            },
            "id": 1,
        }

        if agent_id:
            payload["params"]["message"]["agentId"] = agent_id

        headers = {"Content-Type": "application/json"}
        token = peer.get("token")
        if token:
            headers["Authorization"] = f"Bearer {token}"

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(endpoint, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()


# =============================================================================
# A2A Server (background uvicorn server)
# =============================================================================


class A2AServer:
    """Background HTTP server for A2A inbound messages."""

    def __init__(
        self,
        host: str,
        port: int,
        token: Optional[str],
        agent_card: AgentCard,
        message_handler: Callable[[str], Any],
    ):
        self.host = host
        self.port = port
        self.token = token
        self.agent_card = agent_card
        self.message_handler = message_handler
        self._server: Any = None
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        """Start the A2A HTTP server."""
        try:
            from fastapi import FastAPI, HTTPException, Request
            from fastapi.responses import JSONResponse, StreamingResponse
            import uvicorn

            app = FastAPI(title="A2A Gateway", version="0.3.0")

            @app.get("/.well-known/agent-card.json")
            async def get_agent_card():
                """Return the agent card."""
                return self.agent_card.to_dict()

            @app.get("/health")
            async def health_check():
                """Health check endpoint."""
                return {"status": "ok", "agent": self.agent_card.name}

            @app.post("/a2a/jsonrpc")
            async def handle_jsonrpc(request: Request):
                """Handle JSON-RPC requests."""
                # Check authentication
                if self.token:
                    auth = request.headers.get("Authorization", "")
                    if not auth.startswith("Bearer ") or auth[7:] != self.token:
                        raise HTTPException(status_code=401, detail="Unauthorized")

                body = await request.json()
                method = body.get("method", "")
                request_id = body.get("id")

                if method == "message/send":
                    return await self._handle_message_send(body, request_id)
                elif method == "message/subscribe":
                    return await self._handle_message_subscribe(body, request_id)
                else:
                    raise HTTPException(status_code=404, detail=f"Method '{method}' not supported")

            self._app = app
            config = uvicorn.Config(app, host=self.host, port=self.port, log_level="warning")
            self._server = uvicorn.Server(config)
            self._task = asyncio.create_task(self._server.serve())
            self._running = True

        except ImportError as e:
            raise RuntimeError(
                f"Failed to start A2A server. Missing dependencies: {e}. "
                "Install with: pip install py-code-agent-a2a-gateway"
            ) from e

    async def _handle_message_send(self, body: Dict[str, Any], request_id: Any) -> Dict[str, Any]:
        """Handle message/send JSON-RPC method."""
        params = body.get("params", {})
        msg_data = params.get("message", {})
        message = A2AMessage.from_dict(msg_data)
        text = message.get_text()

        # Call the message handler
        try:
            if asyncio.iscoroutinefunction(self.message_handler):
                response = await self.message_handler(text)
            else:
                response = self.message_handler(text)
        except Exception as e:
            response = f"Error processing message: {e}"

        # Ensure response is a string
        if not isinstance(response, str):
            response = str(response)

        return {
            "jsonrpc": "2.0",
            "result": {
                "message": {
                    "role": "agent",
                    "parts": [{"kind": "text", "text": response}],
                }
            },
            "id": request_id,
        }

    async def _handle_message_subscribe(self, body: Dict[str, Any], request_id: Any) -> Any:
        """Handle message/subscribe JSON-RPC method for SSE streaming."""
        from fastapi.responses import StreamingResponse

        params = body.get("params", {})
        msg_data = params.get("message", {})
        message = A2AMessage.from_dict(msg_data)
        text = message.get_text()

        async def event_generator():
            """Generate SSE events for the response."""
            try:
                if asyncio.iscoroutinefunction(self.message_handler):
                    response = await self.message_handler(text)
                else:
                    response = self.message_handler(text)

                if not isinstance(response, str):
                    response = str(response)

                # Send the response as a single SSE event
                data = {
                    "jsonrpc": "2.0",
                    "result": {
                        "message": {
                            "role": "agent",
                            "parts": [{"kind": "text", "text": response}],
                        }
                    },
                    "id": request_id,
                }
                yield f"data: {json.dumps(data)}\n\n"

            except Exception as e:
                error_data = {
                    "jsonrpc": "2.0",
                    "error": {"code": -32000, "message": str(e)},
                    "id": request_id,
                }
                yield f"data: {json.dumps(error_data)}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    async def stop(self) -> None:
        """Stop the A2A HTTP server."""
        if self._server:
            self._server.should_exit = True
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
        self._running = False

    @property
    def is_running(self) -> bool:
        """Check if the server is running."""
        return self._running


# =============================================================================
# A2A Tools
# =============================================================================


class A2AListPeersTool(BaseTool):
    """List configured A2A peer agents."""

    def __init__(self, client: A2AClient):
        self._client = client

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="a2a_list_peers",
            description="List all configured A2A peer agents with their URLs and authentication status.",
            parameters=[],
        )

    async def execute(self, **kwargs) -> ToolResult:
        peers = self._client.list_peers()
        return ToolResult.ok(
            data={"peers": peers},
            summary=f"Found {len(peers)} configured A2A peers",
        )


class A2ASendMessageTool(BaseTool):
    """Send a message to an A2A peer agent."""

    def __init__(self, client: A2AClient):
        self._client = client

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="a2a_send_message",
            description="Send a message to an A2A peer agent using the A2A protocol.",
            parameters=[
                ToolParameter(
                    name="peer_name",
                    type=ToolParameterType.STRING,
                    description="Name of the peer agent (as configured)",
                    required=True,
                ),
                ToolParameter(
                    name="message",
                    type=ToolParameterType.STRING,
                    description="Message text to send",
                    required=True,
                ),
                ToolParameter(
                    name="agent_id",
                    type=ToolParameterType.STRING,
                    description="Optional agent ID for routing",
                    required=False,
                ),
            ],
        )

    async def execute(
        self,
        peer_name: str,
        message: str,
        agent_id: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        try:
            result = await self._client.send_message(
                peer_name=peer_name,
                message=message,
                agent_id=agent_id,
            )

            # Extract response text if present
            response_text = ""
            if "result" in result:
                msg = result["result"].get("message", {})
                parts = msg.get("parts", [])
                for part in parts:
                    if part.get("kind") == "text":
                        response_text += part.get("text", "")

            return ToolResult.ok(
                data={
                    "response": result,
                    "response_text": response_text,
                },
                summary=f"Message sent to '{peer_name}'. Response: {response_text[:100]}..."
                if len(response_text) > 100
                else f"Message sent to '{peer_name}'. Response: {response_text}",
            )
        except ValueError as e:
            return ToolResult.fail(f"Configuration error: {e}")
        except Exception as e:
            return ToolResult.fail(f"Failed to send message: {e}")


class A2AGetMyCardTool(BaseTool):
    """Get this agent's A2A Agent Card."""

    def __init__(self, server: Optional[A2AServer]):
        self._server = server

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="a2a_get_my_card",
            description="Get this agent's A2A Agent Card containing its name, description, endpoint URL, skills, and capabilities.",
            parameters=[],
        )

    async def execute(self, **kwargs) -> ToolResult:
        if self._server is None:
            return ToolResult.fail("A2A server not initialized")

        card = self._server.agent_card
        return ToolResult.ok(
            data={
                "name": card.name,
                "description": card.description,
                "url": card.url,
                "version": card.version,
                "skills": card.skills,
                "capabilities": card.capabilities,
            },
            summary=f"Agent Card: {card.name} @ {card.url}",
        )


# =============================================================================
# A2A Gateway Plugin
# =============================================================================


class A2AGatewayPlugin:
    """A2A Gateway plugin — enables agent-to-agent communication via A2A protocol v0.3.0.

    This plugin:
    - Exposes HTTP endpoints for A2A protocol
    - Receives inbound messages from peer agents
    - Sends messages to peer agents
    - Provides tools for peer management

    Configuration:
        port: HTTP server port (default: 18800)
        host: HTTP server host (default: 0.0.0.0)
        token: Bearer token for authentication (supports ${ENV_VAR} substitution)
        name: Agent name (default: PyCodeAgent)
        description: Agent description
        skills: List of skill definitions
        peers: List of peer configurations
    """

    def __init__(self):
        self.client = A2AClient()
        self.server: Optional[A2AServer] = None
        self._agent_ref: Optional[Any] = None
        self._pending_responses: Dict[str, asyncio.Future] = {}
        self._config: Dict[str, Any] = {}
        self._logger = None  # Set when available

    def configure(
        self,
        port: int = 18800,
        host: str = "0.0.0.0",
        token: Optional[str] = None,
        name: str = "PyCodeAgent",
        description: str = "Py Code Agent with A2A support",
        skills: Optional[List[Dict[str, str]]] = None,
        peers: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Configure the A2A Gateway plugin.

        Args:
            port: HTTP server port
            host: HTTP server host
            token: Bearer token for authentication (supports ${ENV_VAR})
            name: Agent name
            description: Agent description
            skills: List of skill definitions
            peers: List of peer configurations
        """
        # Substitute environment variables in token
        token = _substitute_env_vars(token) if token else None

        self._config = {
            "port": port,
            "host": host,
            "token": token,
            "name": name,
            "description": description,
            "skills": skills or [],
            "peers": peers or [],
        }

    async def _handle_inbound_message(self, text: str) -> str:
        """Handle an inbound A2A message.

        This method is called by the A2A server when a message is received.
        It delegates to the agent's run() method if available.

        Args:
            text: The message text

        Returns:
            Response text
        """
        if self._agent_ref is None:
            return "Agent not initialized. Cannot process inbound message."

        try:
            # Run the agent and collect events
            events = []
            async for event in self._agent_ref.run(text):
                events.append(event)

            # Extract response from events
            response = ""
            for event in events:
                if hasattr(event, "data"):
                    data = event.data
                    if isinstance(data, dict):
                        if data.get("type") == "content":
                            response += data.get("content", "")
                        elif "content" in data:
                            response += str(data["content"])
                    elif isinstance(data, str):
                        response += data

            return response.strip() or "Message processed."

        except Exception as ex:
            return f"Error processing message: {ex}"

    @hookimpl
    def register_tools(self) -> List[BaseTool]:
        """Register A2A tools.

        Returns tools for peer management and messaging.
        """
        tools: List[BaseTool] = [
            A2AListPeersTool(self.client),
            A2ASendMessageTool(self.client),
        ]

        # Add get_my_card tool if server is initialized
        if self.server is not None:
            tools.append(A2AGetMyCardTool(self.server))
        else:
            # Return placeholder that will work after server starts
            tools.append(A2AGetMyCardTool(None))

        return tools

    @hookimpl
    def on_agent_start(self, input: str) -> None:
        """Called when agent starts.

        Initializes the A2A server and configures peers.
        """
        import asyncio

        # Configure peers from config
        for peer in self._config.get("peers", []):
            name = peer.get("name", "")
            if not name:
                continue

            # Get URL (supports both agentCardUrl and url)
            url = peer.get("agentCardUrl", peer.get("url", ""))

            # Get token (supports nested auth object or direct token)
            token = peer.get("token", "")
            if not token and "auth" in peer:
                token = peer["auth"].get("token", "")

            # Substitute environment variables
            url = _substitute_env_vars(url)
            token = _substitute_env_vars(token) if token else None

            self.client.add_peer(name=name, agent_card_url=url, token=token)

        # Create agent card
        card = AgentCard(
            name=self._config.get("name", "PyCodeAgent"),
            description=self._config.get("description", "Py Code Agent with A2A support"),
            url=f"http://{self._config.get('host', '0.0.0.0')}:{self._config.get('port', 18800)}/a2a/jsonrpc",
            skills=self._config.get("skills", []),
            capabilities={"streaming": True, "async": True},
        )

        # Create and start server
        self.server = A2AServer(
            host=self._config.get("host", "0.0.0.0"),
            port=self._config.get("port", 18800),
            token=self._config.get("token"),
            agent_card=card,
            message_handler=self._handle_inbound_message,
        )

        # Start server in background
        try:
            loop = asyncio.get_event_loop()
            asyncio.create_task(self.server.start())
        except RuntimeError:
            # No event loop running, use run
            asyncio.run(self.server.start())

        # Get agent reference if available (for message handling)
        # This would be set by the agent framework

    @hookimpl
    def on_agent_end(self) -> None:
        """Called when agent ends.

        Stops the A2A server gracefully.
        """
        if self.server is not None:
            import asyncio

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self.server.stop())
                else:
                    asyncio.run(self.server.stop())
            except RuntimeError:
                pass

    def set_agent(self, agent: Any) -> None:
        """Set the agent reference for message handling.

        This should be called by the agent framework when the plugin is loaded.
        """
        self._agent_ref = agent


# Plugin entry point for pluggy
Plugin = A2AGatewayPlugin
