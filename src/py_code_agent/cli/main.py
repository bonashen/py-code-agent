"""CLI main module."""

import asyncio
import sys
import logging
from typing import Optional

import click
from rich.console import Console

logger = logging.getLogger(__name__)

from py_code_agent.cli.config import config_group as config_cmd
from py_code_agent.cli.plugin import plugin_group as plugin_cmd
from py_code_agent.config.models import Config, WebChannelConfig
from py_code_agent.core.agent import Agent
from py_code_agent.channels import ChannelResponse, BaseChannel
from py_code_agent.channels.websocket import WebSocketChannel


console = Console()


def _build_channel_config(
    host: Optional[str],
    port: Optional[int],
    api_keys: tuple,
    no_auth: bool,
    channel_config: Optional[WebChannelConfig],
) -> dict:
    """Build agent config from CLI options and channel config."""
    agent_config = {}
    
    if host:
        agent_config["host"] = host
    elif channel_config and hasattr(channel_config, "host"):
        agent_config["host"] = channel_config.host
    
    if port:
        agent_config["port"] = port
    elif channel_config and hasattr(channel_config, "port"):
        agent_config["port"] = channel_config.port
    
    if api_keys:
        agent_config["api_keys"] = list(api_keys)
    elif channel_config and hasattr(channel_config, "api_keys") and channel_config.api_keys:
        agent_config["api_keys"] = list(channel_config.api_keys)
    
    if no_auth:
        agent_config["require_auth"] = False
    elif channel_config and hasattr(channel_config, "require_auth"):
        agent_config["require_auth"] = channel_config.require_auth
    
    return agent_config


async def run_agent_on_channel(
    channel: BaseChannel,
    agent: Agent,
    channel_name: str,
) -> None:
    """Run agent on a channel, handling message loop and responses."""
    async for msg in channel.receive():
        logger.debug("Received: %s...", msg.content[:50])
        logger.debug("%s_id: %s", channel_name, msg.metadata.get('client_id' if channel_name == 'websocket' else 'channel_id') if msg.metadata else None)
        logger.debug("msg.metadata full: %s", msg.metadata)
        
        await channel.send_status("processing", msg.channel_id, msg.metadata)
        
        client_id = msg.metadata.get("client_id") if msg.metadata else None
        
        context_parts = []
        if hasattr(channel, "get_channel_prompt"):
            context_parts.append(channel.get_channel_prompt())
        if client_id:
            context_parts.append(f"[Current Client: {client_id}]")
        
        context_prefix = " ".join(context_parts) + " " if context_parts else ""
        full_content = context_prefix + msg.content
        
        full_response = ""
        event_count = 0
        async for event in agent.run(full_content):
            if event.type.value == "content":
                full_response += event.data.get("content", "")
                event_count += 1
                if event_count % 5 == 0:
                    await channel.send_status("thinking", msg.channel_id, msg.metadata)
        
        if full_response:
            logger.debug("Sending response (%d chars)", len(full_response))
            response_metadata = {**msg.metadata, "status": "done"} if msg.metadata else {"status": "done"}
            logger.debug("response_metadata: %s", response_metadata)
            logger.debug("response_metadata client_id: %s", response_metadata.get('client_id'))
            logger.debug("About to call channel.send()")
            await channel.send(ChannelResponse(
                content=full_response,
                channel_id=msg.channel_id,
                metadata=response_metadata
            ))
            logger.debug("channel.send() completed")


@click.group()
@click.version_option(version="0.1.0", prog_name="py-code-agent")
@click.option("--config", "-c", type=click.Path(), help="Configuration file path")
@click.pass_context
def cli(ctx: click.Context, config: Optional[str]) -> None:
    """Py Code Agent - AI Coding Assistant"""
    ctx.ensure_object(dict)
    
    # Load configuration
    if config:
        ctx.obj["config"] = Config.from_file(config)
    else:
        ctx.obj["config"] = Config.from_env()


@cli.group()
@click.pass_context
def channel(ctx: click.Context) -> None:
    """Channel commands (websocket, chat)"""
    pass


@channel.command("chat")
@click.option("--model", "-m", help="Model to use")
@click.pass_context
def channel_chat(ctx: click.Context, model: Optional[str]) -> None:
    """Start interactive chat session"""
    config = ctx.obj["config"]
    
    if model:
        config.llm.model = model
    
    console.print("[bold green]Py Code Agent[/bold green]")
    console.print(f"[dim]Model: {config.llm.model}[/dim]")
    console.print("[dim]Type 'exit' or 'quit' to exit[/dim]")
    console.print()
    
    agent = Agent(config)
    
    async def run_chat() -> None:
        while True:
            try:
                user_input = console.input("[bold blue]You:[/bold blue] ")
                
                if user_input.lower() in ("exit", "quit", "q"):
                    console.print("[dim]Goodbye![/dim]")
                    break
                
                if not user_input.strip():
                    continue
                
                console.print("[bold green]Assistant:[/bold green] ", end="")
                
                async for event in agent.run(user_input):
                    if event.type.value == "content":
                        content = event.data.get("content", "")
                        console.print(content, end="")
                
                console.print()
                console.print()
                
            except KeyboardInterrupt:
                console.print("\n[dim]Interrupted. Goodbye![/dim]")
                break
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
    
    asyncio.run(run_chat())


@cli.command()
@click.argument("prompt")
@click.option("--model", "-m", help="Model to use")
@click.pass_context
def run(ctx: click.Context, prompt: str, model: Optional[str]) -> None:
    """Run a single prompt"""
    config = ctx.obj["config"]
    
    if model:
        config.llm.model = model
    
    agent = Agent(config)
    
    async def execute() -> None:
        async for event in agent.run(prompt):
            if event.type.value == "content":
                content = event.data.get("content", "")
                console.print(content, end="")
        console.print()
    
    asyncio.run(execute())


@channel.command("websocket")
@click.option("--model", "-m", help="Model to use")
@click.option("--host", default="0.0.0.0", help="WebSocket server host (default: 0.0.0.0)")
@click.option("--port", "-p", default=8080, type=int, help="WebSocket server port (default: 8080)")
@click.option("--api-key", "api_keys", multiple=True, help="API keys for authentication (can be repeated)")
@click.option("--no-auth", is_flag=True, help="Disable authentication")
@click.pass_context
def channel_websocket(ctx: click.Context, model: Optional[str], host: str, port: int, api_keys: tuple, no_auth: bool) -> None:
    """Start WebSocket channel server"""
    config = ctx.obj["config"]
    
    if model:
        config.llm.model = model
    
    ws_config = config.channels.websocket if config.channels else None
    
    agent_config = _build_channel_config(host, port, api_keys, no_auth, ws_config)
    ws_channel = WebSocketChannel(config, agent_config if agent_config else None)
    
    async def run_websocket():
        await ws_channel.start()
        logger.info("WebSocket channel started on ws://%s:%s/ws", host, port)
        logger.debug("ws_channel._running = %s", ws_channel._running)
        logger.debug("ws_channel._transport = %s", ws_channel._transport)
        logger.debug("ws_channel._transport._websockets = %s", ws_channel._transport._websockets)
        logger.debug("About to call run_agent_on_channel")
        if not no_auth:
            logger.info("Authentication: enabled (%d keys)", len(api_keys))
        else:
            logger.info("Authentication: disabled")
        logger.info("Press Ctrl+C to stop")
        
        agent = Agent(config)
        for tool in ws_channel.get_channel_tools():
            agent.register_tool(tool)
        await run_agent_on_channel(ws_channel, agent, "websocket")
    
    try:
        asyncio.run(run_websocket())
    except KeyboardInterrupt:
        logger.info("\nStopping...")
        asyncio.run(ws_channel.stop())


@cli.command("ws-test")
@click.option("--host", default="127.0.0.1", help="WebSocket server host")
@click.option("--port", "-p", default=8080, type=int, help="WebSocket server port")
@click.option("--api-key", help="API key for authentication")
@click.option("--no-auth", is_flag=True, help="Disable authentication")
@click.pass_context
def ws_test(ctx: click.Context, host: str, port: int, api_key: Optional[str], no_auth: bool) -> None:
    """Test WebSocket channel with interactive client"""
    try:
        import websockets
    except ImportError:
        console.print("[red]websockets package required. Install with: pip install websockets[/red]")
        return
    
    import json
    
    config = ctx.obj["config"]
    
    from py_code_agent.channels.websocket import WebSocketChannel
    
    agent_config = {
        "host": host,
        "port": port,
        "require_auth": not no_auth
    }
    if api_key:
        agent_config["api_keys"] = [api_key]
    
    ws_channel = WebSocketChannel(config, agent_config)
    
    async def run_test():
        await ws_channel.start()
        
        server_url = f"ws://{host}:{port}/ws"
        console.print(f"[green]WebSocket server started: {server_url}[/green]")
        console.print("[yellow]Starting test client...[/yellow]")
        
        try:
            async with websockets.connect(server_url) as websocket:
                console.print("[green]Connected to WebSocket server![/green]")
                
                if not no_auth and api_key:
                    await websocket.send(json.dumps({
                        "type": "auth",
                        "api_key": api_key,
                        "user_id": "test_user"
                    }))
                    response = await websocket.recv()
                    auth_resp = json.loads(response)
                    if auth_resp.get("success"):
                        console.print(f"[green]Authenticated! Session: {auth_resp.get('session_id')}[/green]")
                    else:
                        console.print(f"[red]Auth failed: {auth_resp.get('error')}[/red]")
                        return
                
                test_messages = [
                    {"type": "message", "content": "Hello, this is a test message"},
                    {"type": "message", "content": "What is 2+2?"},
                ]
                
                for i, msg in enumerate(test_messages):
                    console.print(f"[cyan]Sending: {msg['content']}[/cyan]")
                    await websocket.send(json.dumps(msg))
                    
                    try:
                        response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                        console.print(f"[green]Received: {response}[/green]")
                    except asyncio.TimeoutError:
                        console.print("[yellow]Timeout waiting for response[/yellow]")
                
                console.print("[green]WebSocket test completed successfully![/green]")
                
        except websockets.exceptions.ConnectionRefusedError:
            console.print("[red]Connection refused - is the server running?[/red]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
        finally:
            await ws_channel.stop()
    
    asyncio.run(run_test())


def main() -> None:
    """Main entry point."""
    try:
        cli.add_command(plugin_cmd)
        cli()
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
