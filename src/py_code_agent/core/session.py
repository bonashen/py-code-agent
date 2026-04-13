"""Session management with tree/branch support."""

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class SessionNode:
    """Session tree node."""
    
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parent_id: Optional[str] = None
    message: Dict[str, Any] = field(default_factory=dict)
    children: List[str] = field(default_factory=list)
    label: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass
class Session:
    """Session with tree/branch support (对标 pi-coding-agent)."""
    
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    nodes: Dict[str, SessionNode] = field(default_factory=dict)
    current_node_id: Optional[str] = None
    root_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "metadata": self.metadata,
            "nodes": {k: self._node_to_dict(v) for k, v in self.nodes.items()},
            "current_node_id": self.current_node_id,
            "root_id": self.root_id,
        }
    
    def _node_to_dict(self, node: SessionNode) -> Dict[str, Any]:
        """Convert node to dictionary."""
        return {
            "id": node.id,
            "parent_id": node.parent_id,
            "message": node.message,
            "children": node.children,
            "label": node.label,
            "metadata": node.metadata,
            "created_at": node.created_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Session":
        """Create from dictionary."""
        session = cls(
            session_id=data.get("session_id", str(uuid.uuid4())),
            created_at=data.get("created_at", time.time()),
            metadata=data.get("metadata", {}),
            current_node_id=data.get("current_node_id"),
            root_id=data.get("root_id"),
        )
        
        # Reconstruct nodes
        nodes_data = data.get("nodes", {})
        for node_id, node_data in nodes_data.items():
            session.nodes[node_id] = SessionNode(
                id=node_data.get("id", node_id),
                parent_id=node_data.get("parent_id"),
                message=node_data.get("message", {}),
                children=node_data.get("children", []),
                label=node_data.get("label"),
                metadata=node_data.get("metadata", {}),
                created_at=node_data.get("created_at", time.time()),
            )
        
        return session
    
    def add_message(self, role: str, content: str, **kwargs: Any) -> str:
        """Add a message and return node ID."""
        node_id = str(uuid.uuid4())
        message = {
            "role": role,
            "content": content,
            "timestamp": time.time(),
        }
        message.update(kwargs)
        
        node = SessionNode(
            id=node_id,
            parent_id=self.current_node_id,
            message=message,
        )
        
        # Link to parent
        if self.current_node_id and self.current_node_id in self.nodes:
            self.nodes[self.current_node_id].children.append(node_id)
        
        self.nodes[node_id] = node
        
        # Set as root if first message
        if not self.root_id:
            self.root_id = node_id
        
        self.current_node_id = node_id
        return node_id
    
    def get_current_context(self) -> List[Dict[str, Any]]:
        """Get messages along the current branch path."""
        if not self.current_node_id:
            return []
        
        path = []
        current = self.current_node_id
        while current:
            node = self.nodes.get(current)
            if node:
                path.append(node.message)
                current = node.parent_id
            else:
                break
        
        return list(reversed(path))
    
    def fork(self, node_id: str, label: Optional[str] = None) -> str:
        """Fork session from specified node."""
        if node_id not in self.nodes:
            raise ValueError(f"Node {node_id} not found")
        
        # Switch to the node and add a fork marker
        self.current_node_id = node_id
        fork_node_id = self.add_message(
            "system",
            f"[Forked from node {node_id}]",
            label=label or f"Fork from {node_id[:8]}"
        )
        
        return fork_node_id
    
    def switch(self, node_id: str) -> None:
        """Switch to a different node."""
        if node_id not in self.nodes:
            raise ValueError(f"Node {node_id} not found")
        self.current_node_id = node_id
    
    def get_tree(self) -> Dict[str, Any]:
        """Get session tree structure."""
        if not self.root_id:
            return {}
        
        def build_tree(node_id: str) -> Dict[str, Any]:
            node = self.nodes[node_id]
            return {
                "id": node.id,
                "label": node.label,
                "message_preview": node.message.get("content", "")[:100],
                "created_at": node.created_at,
                "children": [build_tree(cid) for cid in node.children],
            }
        
        return build_tree(self.root_id)
    
    def get_recent_messages(self, count: int = 10) -> List[Dict[str, Any]]:
        """Get recent messages from current branch."""
        context = self.get_current_context()
        return context[-count:]
    
    def clear_messages(self) -> None:
        """Clear all messages."""
        self.nodes = {}
        self.current_node_id = None
        self.root_id = None
    
    def compact(self, max_messages: int = 50) -> List[Dict[str, Any]]:
        """Compact session to keep only recent messages."""
        context = self.get_current_context()
        if len(context) <= max_messages:
            return context
        
        # Keep first message (root) and last N messages
        compacted = [context[0]] + context[-(max_messages-1):]
        return compacted
    
    def save_to_file(self, path: Path) -> None:
        """Save session to JSONL file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            json.dump(self.to_dict(), f)
    
    @classmethod
    def load_from_file(cls, path: Path) -> "Session":
        """Load session from JSONL file."""
        with open(path, 'r') as f:
            data = json.load(f)
        return cls.from_dict(data)
