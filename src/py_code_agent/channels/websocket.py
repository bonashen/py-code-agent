import asyncio
import uuid
from typing import Optional, Any, Dict, List
from collections.abc import AsyncIterator

from py_code_agent.channels import BaseChannel, ChannelMessage, ChannelResponse, ChannelType
from py_code_agent.channels.core import AuthManager, SessionManager, JsonCodec
from py_code_agent.channels.transport import WebSocketTransport
from py_code_agent.config.models import Config
from py_code_agent.tools.base import BaseTool, ToolDefinition, ToolParameter, ToolParameterType, ToolResult


class SendMessageTool(BaseTool):
    """Tool to send message to specific client."""
    
    def __init__(self, channel):
        self.channel = channel
    
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="send_message",
            description="Send a message to a specific client via WebSocket",
            parameters=[
                ToolParameter(
                    name="client_id",
                    type=ToolParameterType.STRING,
                    description="The client ID to send message to",
                    required=True
                ),
                ToolParameter(
                    name="message",
                    type=ToolParameterType.STRING,
                    description="Message content to send",
                    required=True
                ),
            ],
        )
    
    async def execute(self, client_id: str, message: str, **kwargs) -> ToolResult:
        try:
            response = ChannelResponse(content=message, channel_id=f"ws_{client_id}", metadata={"type": "message"})
            await self.channel.send_to_client(client_id, response)
            return ToolResult.ok(data={"sent": True, "client_id": client_id, "message": message})
        except Exception as e:
            return ToolResult.fail(str(e))


class SendFileTool(BaseTool):
    """Tool to send file content to specific client."""
    
    def __init__(self, channel):
        self.channel = channel
    
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="send_file",
            description="Send file content to a specific client via WebSocket",
            parameters=[
                ToolParameter(
                    name="client_id",
                    type=ToolParameterType.STRING,
                    description="The client ID to send file to",
                    required=True
                ),
                ToolParameter(
                    name="file_path",
                    type=ToolParameterType.STRING,
                    description="Path to the file to send",
                    required=True
                ),
            ],
        )
    
    async def execute(self, client_id: str, file_path: str, **kwargs) -> ToolResult:
        try:
            import aiofiles
            import base64
            
            async with aiofiles.open(file_path, 'rb') as f:
                content_bytes = await f.read()
            
            content_b64 = base64.b64encode(content_bytes).decode('utf-8')
            filename = file_path.split('/')[-1]
            
            response = ChannelResponse(
                content=content_b64,
                channel_id=f"ws_{client_id}",
                metadata={
                    "file_path": file_path,
                    "filename": filename,
                    "type": "file"
                }
            )
            await self.channel.send_to_client(client_id, response)
            return ToolResult.ok(data={"sent": True, "client_id": client_id, "file_path": file_path, "filename": filename})
        except Exception as e:
            return ToolResult.fail(str(e))


class WebSocketChannel(BaseChannel):

    def __init__(self, config: Config, agent_config: Optional[dict] = None):
        super().__init__(config, agent_config)
        self.host = agent_config.get("host", "0.0.0.0") if agent_config else "0.0.0.0"
        self.port = agent_config.get("port", 8080) if agent_config else 8080
        
        api_keys = agent_config.get("api_keys", []) if agent_config else []
        if isinstance(api_keys, str):
            api_keys = [api_keys]
        
        self._auth_manager = AuthManager(
            api_keys=set(api_keys),
            require_auth=agent_config.get("require_auth", True) if agent_config else True
        )
        self._session_manager = SessionManager()
        self._codec = JsonCodec()
        
        self._transport = WebSocketTransport(
            host=self.host,
            port=self.port,
            message_handler=self._handle_message
        )
        self._message_queue: asyncio.Queue[ChannelMessage] = asyncio.Queue()
        self._client_auth: Dict[str, dict[str, Any]] = {}

    @property
    def channel_type(self) -> ChannelType:
        return ChannelType.WEBSOCKET

    async def connect(self) -> None:
        await self._transport.start()
        print(f"WebSocket server started on ws://{self.host}:{self.port}/ws")
        if self._auth_manager.require_auth:
            print(f"Authentication enabled: {len(self._auth_manager._api_keys)} API keys configured")

    async def disconnect(self) -> None:
        await self._transport.stop()
        self._client_auth.clear()

    async def _handle_message(self, msg: dict[str, Any], client_id: str) -> None:
        print(f"[DEBUG] _handle_message: {msg}, client_id: {client_id}")
        msg_type = msg.get("type", "message")
        
        if msg_type == "auth":
            api_key = msg.get("api_key", "")
            
            if self._auth_manager.verify_api_key(api_key):
                token = self._auth_manager.generate_token(msg.get("user_id", "ws_user"))
                user_id = msg.get("user_id", "ws_user")
                session_id = msg.get("session_id")
                message_id = msg.get("message_id") or uuid.uuid4().hex.upper()
                
                session = self._session_manager.create_session(user_id, session_id)
                
                self._client_auth[client_id] = {
                    "user_id": user_id,
                    "token": token,
                    "session_id": session.session_id,
                    "message_id": message_id
                }
                
                await self._transport.send({
                    "type": "auth_response",
                    "success": True,
                    "token": token,
                    "session_id": session.session_id,
                    "message_id": message_id
                }, client_id)
                
                print(f"Client authenticated: {client_id} (user: {user_id})")
            else:
                await self._transport.send({
                    "type": "auth_response",
                    "success": False,
                    "error": "Invalid API key"
                }, client_id)
                print(f"Authentication failed: {client_id}")
        
        elif msg_type == "message":
            if self._auth_manager.require_auth and client_id not in self._client_auth:
                await self._transport.send({
                    "type": "error",
                    "message": "Authentication required"
                }, client_id)
                return
            
            user_id = msg.get("user_id", "ws_user")
            session_id = msg.get("session_id")
            
            if client_id in self._client_auth:
                auth_info = self._client_auth[client_id]
                user_id = auth_info["user_id"]
                session_id = session_id or auth_info.get("session_id")
            
            content = msg.get("content") or msg.get("message", "")
            
            if session_id:
                self._session_manager.add_message(session_id, "user", content)
            
            channel_msg = ChannelMessage(
                content=content,
                user_id=user_id,
                channel_id=f"ws_{client_id}",
                message_id=msg.get("message_id"),
                metadata={
                    **msg.get("metadata", {}),
                    "session_id": session_id,
                    "client_id": client_id
                }
            )
            print(f"[DEBUG] _handle_message: put to queue, client_id={client_id}, metadata client_id={channel_msg.metadata.get('client_id')}")
            await self._message_queue.put(channel_msg)

    async def receive(self):  # type: ignore[override]
        print("[DEBUG] receive() generator started")
        while self._running:
            try:
                msg = await asyncio.wait_for(self._message_queue.get(), timeout=1.0)
                print(f"[DEBUG] receive: got message from queue: {msg.content[:50]}...")
                print(f"[DEBUG] receive: msg.metadata = {msg.metadata}")
                yield msg
            except asyncio.TimeoutError:
                continue

    async def send(self, response: ChannelResponse) -> None:
        session_id = response.metadata.get("session_id") if response.metadata else None
        client_id = response.metadata.get("client_id") if response.metadata else None
        response.message_id = response.message_id or uuid.uuid4().hex.upper()
        
        print(f"[DEBUG] send() called: client_id={client_id}, metadata={response.metadata}")
        print(f"[DEBUG] send() channel_id={response.channel_id}")
        print(f"[DEBUG] send() message_id={response.message_id}")
        
        if session_id:
            self._session_manager.add_message(session_id, "assistant", response.content)
        
        encoded = self._codec.encode(response)
        
        if client_id:
            print(f"[DEBUG] send() calling transport.send() to {client_id}")
            await self._transport.send({
                "type": "message",
                "message": response.content,
                "channel_id": response.channel_id,
                "message_id": response.message_id,
                "metadata": response.metadata
            }, client_id)
            print(f"[DEBUG] send() transport.send() completed")
        else:
            print(f"[DEBUG] send() calling transport.broadcast()")
            await self._transport.broadcast({
                "type": "message",
                "message": response.content,
                "channel_id": response.channel_id,
                "message_id": response.message_id,
                "metadata": response.metadata
            })

    async def send_to_client(self, client_id: str, response: ChannelResponse) -> None:
        session_id = response.metadata.get("session_id") if response.metadata else None
        
        if session_id:
            self._session_manager.add_message(session_id, "assistant", response.content)
        
        msg_type = response.metadata.get("type", "message") if response.metadata else "message"
        
        msg_payload = {
            "type": msg_type,
            "channel_id": response.channel_id,
            "message_id": response.message_id or uuid.uuid4().hex.upper(),
            "session_id": session_id,
            "metadata": response.metadata
        }
        
        if msg_type == "file":
            msg_payload["file"] = response.content
        elif msg_type == "status":
            msg_payload["status"] = response.metadata.get("status", "done") if response.metadata else "done"
        else:
            msg_payload["message"] = response.content
        
        await self._transport.send(msg_payload, client_id)

    def get_session_history(self, session_id: str) -> list[dict[str, Any]]:
        return self._session_manager.get_history(session_id)

    async def broadcast(self, content: str) -> None:
        response = ChannelResponse(content=content, channel_id="broadcast")
        await self.send(response)

    async def send_status(self, status: str, channel_id: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        session_id = metadata.get("session_id") if metadata else None
        client_id = metadata.get("client_id") if metadata else None
        
        status_msg = {
            "type": "status",
            "status": status,
            "channel_id": channel_id
        }
        if metadata:
            status_msg["metadata"] = metadata
        if session_id:
            status_msg["session_id"] = session_id
        
        if client_id:
            await self._transport.send(status_msg, client_id)
        else:
            await self._transport.broadcast(status_msg)
    
    def get_channel_prompt(self) -> str:
        return """You are a WebSocket Channel assistant.
Keep users informed during task execution:
- Use send_message to send progress updates to users while working on tasks
- Use send_file to send file content to users when required

Note: Always use the current client's client_id when sending messages or files.

## Critical: Tool Call JSON Format
When calling tools, you MUST use valid JSON format:
- ALWAYS use double quotes for keys and string values
- NEVER duplicate keys in the same object: {"a":1,"a":2} is INVALID
- For multi-line content, use execute_bash with HEREDOC instead of write_file

## Error Recovery
If your tool call fails with "Invalid JSON", analyze the error and retry with corrected JSON.
Do NOT repeat the same malformed call.

## Mandatory: assess_complexity
Before executing ANY task, you MUST call assess_complexity first.

## Task Completion Protocol
After completing the user's task, you MUST:
1. Call send_message with the final result/interpretation
2. Call task_done to formally complete the task
- task_done parameters: original_task, expected_output, verification_context
Example:
  send_message({"client_id": "...", "message": "Here is the analysis..."})
  task_done({"original_task": "解读 pyproject.toml", "expected_output": "文件内容解读", "verification_context": "已完成文件读取和解读"})"""
    
    def get_channel_tools(self) -> List[BaseTool]:
        return [
            SendMessageTool(self),
            SendFileTool(self),
        ]
