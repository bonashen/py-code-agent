"""Session tree and branch commands implementation."""

import json
import time
from typing import Any, Dict, List, Optional, AsyncIterator
from rich.console import Console
from rich.tree import Tree
from rich.text import Text

from py_code_agent.core.session import Session
from py_code_agent.core.events import Event, EventType

console = Console()


class SessionCommands:
    """Session tree/branch commands (/tree, /fork, /switch)."""
    
    def __init__(self, session: Session):
        self.session = session
    
    async def handle_command(self, command: str) -> AsyncIterator[Event]:
        """Handle session commands."""
        parts = command.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        
        if cmd == "/tree":
            async for event in self.cmd_tree(args):
                yield event
        elif cmd == "/fork":
            async for event in self.cmd_fork(args):
                yield event
        elif cmd == "/switch":
            async for event in self.cmd_switch(args):
                yield event
        elif cmd == "/compact":
            async for event in self.cmd_compact(args):
                yield event
        else:
            yield Event(
                type=EventType.ERROR,
                data={"error": f"Unknown command: {cmd}"}
            )
    
    async def cmd_tree(self, args: str) -> AsyncIterator[Event]:
        """Display session tree structure."""
        tree_data = self.session.get_tree()
        
        if not tree_data:
            yield Event(
                type=EventType.CONTENT,
                data={"content": "🌳 Session tree is empty. Start a conversation first."}
            )
            return
        
        # Build rich tree visualization
        def build_rich_tree(node: Dict[str, Any], depth: int = 0) -> Tree:
            label = node.get("label") or f"Node {node['id'][:8]}"
            preview = node.get("message_preview", "")
            if preview:
                preview = preview[:50] + "..." if len(preview) > 50 else preview
                label = f"{label}: {preview}"
            
            tree = Tree(label)
            for child in node.get("children", []):
                tree.add(build_rich_tree(child, depth + 1))
            return tree
        
        rich_tree = build_rich_tree(tree_data)
        
        # Convert to string for event
        from io import StringIO
        output = StringIO()
        console.file = output
        console.print(rich_tree)
        tree_str = output.getvalue()
        console.file = None
        
        yield Event(
            type=EventType.SESSION_TREE,
            data={
                "tree": tree_data,
                "visualization": tree_str,
                "current_node": self.session.current_node_id
            }
        )
        
        yield Event(
            type=EventType.CONTENT,
            data={"content": f"🌳 Session Tree (Current: {self.session.current_node_id[:8] if self.session.current_node_id else 'None'})\n{tree_str}"}
        )
    
    async def cmd_fork(self, args: str) -> AsyncIterator[Event]:
        """Fork session from specified node."""
        if not args:
            # Fork from current node
            if not self.session.current_node_id:
                yield Event(
                    type=EventType.ERROR,
                    data={"error": "No current node to fork from. Add a message first."}
                )
                return
            node_id = self.session.current_node_id
        else:
            # Fork from specified node ID
            node_id = args.strip()
        
        try:
            fork_node_id = self.session.fork(node_id)
            
            yield Event(
                type=EventType.SESSION_FORK,
                data={
                    "forked_from": node_id,
                    "new_node_id": fork_node_id,
                    "timestamp": time.time()
                }
            )
            
            yield Event(
                type=EventType.CONTENT,
                data={
                    "content": f"🔀 Forked session from node {node_id[:8]}...\n   New branch node: {fork_node_id[:8]}\n   Use /tree to see the updated session tree."
                }
            )
            
        except ValueError as e:
            yield Event(
                type=EventType.ERROR,
                data={"error": str(e)}
            )
    
    async def cmd_switch(self, args: str) -> AsyncIterator[Event]:
        """Switch to a different node."""
        if not args:
            yield Event(
                type=EventType.ERROR,
                data={"error": "Usage: /switch <node_id>"}
            )
            return
        
        node_id = args.strip()
        
        try:
            self.session.switch(node_id)
            
            yield Event(
                type=EventType.SESSION_SWITCH,
                data={
                    "switched_to": node_id,
                    "timestamp": time.time()
                }
            )
            
            # Get context after switch
            context = self.session.get_current_context()
            msg_count = len(context)
            
            yield Event(
                type=EventType.CONTENT,
                data={
                    "content": f"🔄 Switched to node {node_id[:8]}...\n   Context messages: {msg_count}\n   Use /tree to see your position in the session tree."
                }
            )
            
        except ValueError as e:
            yield Event(
                type=EventType.ERROR,
                data={"error": str(e)}
            )
    
    async def cmd_compact(self, args: str) -> AsyncIterator[Event]:
        """Compact session to reduce context size."""
        max_messages = 50
        if args:
            try:
                max_messages = int(args.strip())
            except ValueError:
                yield Event(
                    type=EventType.ERROR,
                    data={"error": "Invalid max_messages. Usage: /compact [max_messages]"}
                )
                return
        
        # Emit before compact event
        context_before = self.session.get_current_context()
        yield Event(
            type=EventType.SESSION_BEFORE_COMPACT,
            data={
                "current_count": len(context_before),
                "max_messages": max_messages
            }
        )
        
        # Compact
        compacted = self.session.compact(max_messages)
        
        # Emit compacted event
        yield Event(
            type=EventType.SESSION_COMPACTED,
            data={
                "original_count": len(context_before),
                "compacted_count": len(compacted),
                "reduced_by": len(context_before) - len(compacted)
            }
        )
        
        if len(context_before) > max_messages:
            yield Event(
                type=EventType.CONTENT,
                data={
                    "content": f"📦 Session compacted: {len(context_before)} → {len(compacted)} messages\n   Reduced by {len(context_before) - len(compacted)} messages."
                }
            )
        else:
            yield Event(
                type=EventType.CONTENT,
                data={
                    "content": f"ℹ️ No compaction needed. Current messages ({len(context_before)}) <= max ({max_messages})."
                }
            )


class CostTracker:
    """Real-time cost tracking for LLM calls."""
    
    # Token pricing (per 1M tokens) - update as needed
    PRICING = {
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4-turbo": {"input": 10.00, "output": 30.00},
        "gpt-4": {"input": 30.00, "output": 60.00},
        "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
        "claude-3-opus": {"input": 15.00, "output": 75.00},
        "claude-3-sonnet": {"input": 3.00, "output": 15.00},
        "claude-3-haiku": {"input": 0.25, "output": 1.25},
        "default": {"input": 1.00, "output": 3.00},  # fallback
    }
    
    def __init__(self, model: str):
        self.model = model
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost = 0.0
        self.turn_costs: List[Dict[str, Any]] = []
        self.current_turn_start: Optional[float] = None
    
    def start_turn(self) -> None:
        """Start tracking a new turn."""
        self.current_turn_start = time.time()
    
    def add_usage(self, input_tokens: int, output_tokens: int = 0) -> float:
        """Add token usage and calculate cost."""
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        
        # Calculate cost
        pricing = self._get_pricing()
        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]
        turn_cost = input_cost + output_cost
        
        self.total_cost += turn_cost
        
        # Record turn
        if self.current_turn_start:
            self.turn_costs.append({
                "timestamp": self.current_turn_start,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost": turn_cost,
                "duration": time.time() - self.current_turn_start
            })
            self.current_turn_start = None
        
        return turn_cost
    
    def _get_pricing(self) -> Dict[str, float]:
        """Get pricing for current model."""
        # Try exact match
        if self.model in self.PRICING:
            return self.PRICING[self.model]
        
        # Try partial match
        for model_name, pricing in self.PRICING.items():
            if model_name in self.model.lower():
                return pricing
        
        # Fallback to default
        return self.PRICING["default"]
    
    def get_summary(self) -> Dict[str, Any]:
        """Get cost summary."""
        return {
            "model": self.model,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
            "total_cost_usd": self.total_cost,
            "turns": len(self.turn_costs),
            "avg_cost_per_turn": self.total_cost / len(self.turn_costs) if self.turn_costs else 0
        }
    
    def format_summary(self) -> str:
        """Format cost summary for display."""
        summary = self.get_summary()
        return (
            f"💰 Cost Summary:\n"
            f"   Model: {summary['model']}\n"
            f"   Total Tokens: {summary['total_tokens']:,} (Input: {summary['total_input_tokens']:,}, Output: {summary['total_output_tokens']:,})\n"
            f"   Total Cost: ${summary['total_cost_usd']:.6f}\n"
            f"   Turns: {summary['turns']}\n"
            f"   Avg Cost/Turn: ${summary['avg_cost_per_turn']:.6f}"
        )
