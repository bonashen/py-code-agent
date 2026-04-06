"""Session management."""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Session:
    """Session data class."""
    
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    messages: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "metadata": self.metadata,
            "messages": self.messages,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Session":
        """Create from dictionary."""
        return cls(
            session_id=data.get("session_id", str(uuid.uuid4())),
            created_at=data.get("created_at", time.time()),
            metadata=data.get("metadata", {}),
            messages=data.get("messages", []),
        )
    
    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        """Add a message to the session."""
        message: Dict[str, Any] = {
            "role": role,
            "content": content,
            "timestamp": time.time(),
        }
        message.update(kwargs)
        self.messages.append(message)
    
    def get_recent_messages(self, count: int = 10) -> List[Dict[str, Any]]:
        """Get recent messages."""
        return self.messages[-count:]
    
    def clear_messages(self) -> None:
        """Clear all messages."""
        self.messages = []
