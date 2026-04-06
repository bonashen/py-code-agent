from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Optional, Callable, Awaitable
import asyncio
import json
import logging

logger = logging.getLogger(__name__)


class Transport(ABC):
    @abstractmethod
    async def start(self) -> None: ...
    
    @abstractmethod
    async def stop(self) -> None: ...
    
    @abstractmethod
    async def send(self, data: dict[str, Any], client_id: Optional[str] = None) -> None: ...
    
    @abstractmethod
    async def broadcast(self, data: dict[str, Any]) -> None: ...
    
    @property
    @abstractmethod
    def is_running(self) -> bool: ...


class TcpTransport(Transport):
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8080,
        message_handler: Optional[Callable[[dict[str, Any], str], Awaitable[None]]] = None,
    ):
        self.host = host
        self.port = port
        self.message_handler = message_handler
        self._server: Optional[asyncio.Server] = None
        self._running = False
        self._clients: dict[asyncio.StreamWriter, str] = {}
    
    @property
    def is_running(self) -> bool:
        return self._running
    
    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_client,
            self.host,
            self.port
        )
        self._running = True
    
    async def stop(self) -> None:
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        for writer in list(self._clients.keys()):
            writer.close()
        self._clients.clear()
    
    async def send(self, data: dict[str, Any], client_id: Optional[str] = None) -> None:
        payload = json.dumps(data).encode() + b"\n"
        for writer, cid in self._clients.items():
            if client_id is None or cid == client_id:
                try:
                    writer.write(payload)
                    await writer.drain()
                except Exception as e:
                    logger.debug(f"Error sending to client {cid}: {e}")
    
    async def broadcast(self, data: dict[str, Any]) -> None:
        await self.send(data, None)
    
    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        addr = writer.get_extra_info("peername")
        client_id = f"{addr[0]}:{addr[1]}"
        self._clients[writer] = client_id
        
        try:
            while self._running:
                data = await reader.readline()
                if not data:
                    break
                try:
                    msg = json.loads(data.decode())
                    if self.message_handler:
                        await self.message_handler(msg, client_id)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass
        except Exception as e:
            logger.debug(f"Client handler error for {client_id}: {e}")
        finally:
            if writer in self._clients:
                del self._clients[writer]
            writer.close()


class HttpTransport(Transport):
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8080,
        message_handler: Optional[Callable[[dict[str, Any], str], Awaitable[None]]] = None,
    ):
        from aiohttp import web
        self.host = host
        self.port = port
        self.message_handler = message_handler
        self._app = web.Application()
        self._runner: Optional[web.AppRunner] = None
        self._running = False
        self._client_sessions: dict[str, dict[str, Any]] = {}
        self._setup_routes()
    
    def _setup_routes(self):
        from aiohttp import web
        self._app.router.add_post("/message", self._handle_message)
        self._app.router.add_get("/health", self._handle_health)
    
    @property
    def is_running(self) -> bool:
        return self._running
    
    async def start(self) -> None:
        from aiohttp import web
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        self._running = True
    
    async def stop(self) -> None:
        self._running = False
        if self._runner:
            await self._runner.cleanup()
    
    async def send(self, data: dict[str, Any], client_id: Optional[str] = None) -> None:
        if client_id and client_id in self._client_sessions:
            session = self._client_sessions[client_id]
            if "websocket" in session:
                try:
                    await session["websocket"].send_json(data)
                except Exception as e:
                    logger.debug(f"Error sending to HTTP client {client_id}: {e}")
    
    async def broadcast(self, data: dict[str, Any]) -> None:
        for client_id in list(self._client_sessions.keys()):
            await self.send(data, client_id)
    
    async def _handle_message(self, request):
        from aiohttp import web
        try:
            msg = await request.json()
            client_id = request.headers.get("X-Client-ID", "http_client")
            
            if self.message_handler:
                await self.message_handler(msg, client_id)
            
            return web.json_response({"status": "ok"})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)
    
    async def _handle_health(self, request):
        from aiohttp import web
        return web.json_response({"status": "healthy"})


class WebSocketTransport(Transport):
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8080,
        message_handler: Optional[Callable[[dict[str, Any], str], Awaitable[None]]] = None,
    ):
        from aiohttp import web
        self.host = host
        self.port = port
        self.message_handler = message_handler
        self._app = web.Application()
        self._runner: Optional[web.AppRunner] = None
        self._running = False
        self._websockets: dict[str, web.WebSocketResponse] = {}
        self._setup_routes()
    
    def _setup_routes(self):
        from aiohttp import web
        self._app.router.add_get("/ws", self._handle_websocket)
        self._app.router.add_get("/health", self._handle_health)
    
    @property
    def is_running(self) -> bool:
        return self._running
    
    async def start(self) -> None:
        from aiohttp import web
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        self._running = True
    
    async def stop(self) -> None:
        self._running = False
        for ws in list(self._websockets.values()):
            await ws.close()
        self._websockets.clear()
        if self._runner:
            await self._runner.cleanup()
    
    async def send(self, data: dict[str, Any], client_id: Optional[str] = None) -> None:
        print(f"[TRANSPORT] send() called: client_id={client_id}, data_type={data.get('type')}")
        print(f"[TRANSPORT] _websockets keys: {list(self._websockets.keys())}")
        if client_id and client_id in self._websockets:
            try:
                print(f"[TRANSPORT] send() to {client_id}: {data}")
                await self._websockets[client_id].send_json(data)
                print(f"[TRANSPORT] send() success to {client_id}")
            except Exception as e:
                print(f"[TRANSPORT] Error sending to WebSocket client {client_id}: {e}")
                import traceback
                traceback.print_exc()
                logger.debug(f"Error sending to WebSocket client {client_id}: {e}")
        else:
            print(f"[TRANSPORT] send() FAILED: client_id {client_id} not in websockets")
    
    async def broadcast(self, data: dict[str, Any]) -> None:
        for client_id in list(self._websockets.keys()):
            await self.send(data, client_id)
    
    async def _handle_websocket(self, request):
        from aiohttp import web
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        
        client_id = request.headers.get("X-Client-ID", f"ws_{id(ws)}")
        print(f"[TRANSPORT] _handle_websocket: new client_id={client_id}, existing websockets={list(self._websockets.keys())}")
        self._websockets[client_id] = ws
        
        try:
            async for msg in ws:
                print(f"[TRANSPORT] Received WS message: {msg}")
                if msg.type == web.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        print(f"[TRANSPORT] Parsed JSON: {data}")
                        if self.message_handler:
                            print(f"[TRANSPORT] Calling message_handler...")
                            await self.message_handler(data, client_id)
                    except json.JSONDecodeError as e:
                        print(f"[TRANSPORT] JSON decode error: {e}")
                        pass
                elif msg.type == web.WSMsgType.ERROR:
                    break
        finally:
            if client_id in self._websockets:
                del self._websockets[client_id]
        
        return ws
    
    async def _handle_health(self, request):
        from aiohttp import web
        return web.json_response({"status": "healthy"})
