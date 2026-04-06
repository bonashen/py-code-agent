"""Event types and streaming events."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional
import time


class EventType(str, Enum):
    """Event types."""
    
    # Content events
    CONTENT = "content"
    THINKING = "thinking"
    
    # Tool events
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    
    # Status events
    START = "start"
    END = "end"
    ERROR = "error"
    READY = "ready"
    
    # System events
    PING = "ping"
    PONG = "pong"


@dataclass
class Event:
    """Event data class."""
    
    type: EventType
    data: Any
    timestamp: float = field(default_factory=time.time)
    metadata: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "type": self.type.value,
            "data": self.data,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Event":
        """Create from dictionary."""
        return cls(
            type=EventType(data["type"]),
            data=data["data"],
            timestamp=data.get("timestamp", time.time()),
            metadata=data.get("metadata"),
        )


@dataclass
class ToolCallEvent:
    """Tool call event data."""
    
    id: str
    name: str
    arguments: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "arguments": self.arguments,
        }


@dataclass
class ToolResultEvent:
    """Tool result event data."""
    
    tool_call_id: str
    success: bool
    data: Any
    error: Optional[str] = None
    summary: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "tool_call_id": self.tool_call_id,
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "summary": self.summary,
        }
