from abc import ABC, abstractmethod
from typing import Any, Optional, AsyncIterator, AsyncGenerator
from dataclasses import dataclass
from enum import Enum

from py_code_agent.config.models import Config


class ChannelType(Enum):
    CLI = "cli"
    WEB = "web"
    WEBSOCKET = "websocket"
    FEISHU = "feishu"
    MATRIX = "matrix"
    SLACK = "slack"
    DISCORD = "discord"


@dataclass
class ChannelMessage:
    content: str
    user_id: str
    channel_id: str
    message_id: Optional[str] = None
    metadata: Optional[dict] = None


@dataclass
class ChannelResponse:
    content: str
    channel_id: str
    message_id: Optional[str] = None
    metadata: Optional[dict] = None


class BaseChannel(ABC):

    def __init__(self, config: Config, agent_config: Optional[dict] = None):
        self.config = config
        self.agent_config = agent_config or {}
        self._running = False

    @property
    @abstractmethod
    def channel_type(self) -> ChannelType:
        pass

    @abstractmethod
    async def connect(self) -> None:
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        pass

    async def receive(self):
        """Receive messages from the channel. Override in subclass."""
        return
        yield

    @abstractmethod
    async def send(self, response: ChannelResponse) -> None:
        pass

    async def start(self) -> None:
        self._running = True
        await self.connect()

    async def stop(self) -> None:
        self._running = False
        await self.disconnect()

    async def send_status(
        self,
        status: str,
        channel_id: str,
        metadata: Optional[dict] = None,
    ) -> None:
        """Send status update to client. Override in subclass for custom behavior."""


class ChannelManager:

    def __init__(self, config: Config):
        self.config = config
        self._channels: dict[ChannelType, BaseChannel] = {}

    def register_channel(self, channel: BaseChannel) -> None:
        self._channels[channel.channel_type] = channel

    def get_channel(self, channel_type: ChannelType) -> Optional[BaseChannel]:
        return self._channels.get(channel_type)

    def list_channels(self) -> list[BaseChannel]:
        return list(self._channels.values())

    async def start_all(self) -> None:
        for channel in self._channels.values():
            await channel.start()

    async def stop_all(self) -> None:
        for channel in self._channels.values():
            await channel.stop()
