from typing import AsyncGenerator, Optional
import asyncio
import sys

from py_code_agent.channels import BaseChannel, ChannelMessage, ChannelResponse, ChannelType
from py_code_agent.config.models import Config
from py_code_agent.core.agent import Agent


class CliChannel(BaseChannel):

    def __init__(self, config: Config, agent_config: Optional[dict] = None):
        super().__init__(config, agent_config)
        self._agent: Optional[Agent] = None
        self._input_queue: asyncio.Queue[ChannelMessage] = asyncio.Queue()
        self._reader: Optional[asyncio.StreamReader] = None

    @property
    def channel_type(self) -> ChannelType:
        return ChannelType.CLI

    async def connect(self) -> None:
        loop = asyncio.get_event_loop()
        self._reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(self._reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    async def disconnect(self) -> None:
        self._reader = None

    async def receive(self):  # type: ignore[override]
        while self._running:
            try:
                if self._reader is None:
                    await asyncio.sleep(0.1)
                    continue
                line = await asyncio.wait_for(self._reader.readline(), timeout=1.0)
                if not line:
                    continue
                content = line.decode().strip()
                if not content:
                    continue
                msg = ChannelMessage(
                    content=content,
                    user_id="cli_user",
                    channel_id="cli"
                )
                yield msg
            except asyncio.TimeoutError:
                continue
            except Exception:
                await asyncio.sleep(0.1)
                continue

    async def send(self, response: ChannelResponse) -> None:
        print(response.content)

    async def push_message(self, content: str, user_id: str = "cli_user") -> None:
        """Async version of push_message for non-blocking message injection."""
        msg = ChannelMessage(
            content=content,
            user_id=user_id,
            channel_id="cli"
        )
        await self._input_queue.put(msg)

    def push_message_sync(self, content: str, user_id: str = "cli_user") -> None:
        """Sync version for backwards compatibility - schedules the message."""
        msg = ChannelMessage(
            content=content,
            user_id=user_id,
            channel_id="cli"
        )
        asyncio.create_task(self._input_queue.put(msg))

    async def run_interactive(self) -> None:
        self._agent = Agent(self.config)
        await self.start()

        print("Py Code Agent (CLI Channel)")
        print("Type 'exit' or 'quit' to exit")
        print("-" * 40)

        while self._running:
            try:
                if self._reader is None:
                    break
                
                # Non-blocking read
                reader_future = self._reader.readline()
                try:
                    line = await asyncio.wait_for(reader_future, timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                
                user_input = line.decode().strip()
                if user_input.lower() in ("exit", "quit", "q"):
                    break

                if not user_input.strip():
                    continue

                print("\nAssistant: ", end="", flush=True)

                async for event in self._agent.run(user_input):
                    if event.type.value == "content":
                        content = event.data.get("content", "")
                        print(content, end="", flush=True)

                print()

            except KeyboardInterrupt:
                print("\nInterrupted. Goodbye!")
                break
            except Exception as e:
                print(f"\nError: {e}")

        await self.stop()
