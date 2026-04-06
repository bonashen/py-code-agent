"""Test agent core functionality."""

import pytest
import asyncio

from py_code_agent.core.agent import Agent
from py_code_agent.core.session import Session
from py_code_agent.core.events import Event, EventType
from py_code_agent.config.models import Config


class TestSession:
    """Test session management."""
    
    def test_session_creation(self):
        """Test session creation."""
        session = Session()
        assert session.session_id is not None
        assert session.messages == []
    
    def test_add_message(self):
        """Test adding messages."""
        session = Session()
        session.add_message("user", "Hello")
        session.add_message("assistant", "Hi there!")
        
        assert len(session.messages) == 2
        assert session.messages[0]["role"] == "user"
        assert session.messages[0]["content"] == "Hello"
    
    def test_get_recent_messages(self):
        """Test getting recent messages."""
        session = Session()
        for i in range(15):
            session.add_message("user", f"Message {i}")
        
        recent = session.get_recent_messages(10)
        assert len(recent) == 10
    
    def test_clear_messages(self):
        """Test clearing messages."""
        session = Session()
        session.add_message("user", "Test")
        session.clear_messages()
        
        assert len(session.messages) == 0


class TestEvent:
    """Test events."""
    
    def test_event_creation(self):
        """Test event creation."""
        event = Event(
            type=EventType.CONTENT,
            data={"content": "Hello"}
        )
        
        assert event.type == EventType.CONTENT
        assert event.data == {"content": "Hello"}
    
    def test_event_to_dict(self):
        """Test event to dictionary conversion."""
        event = Event(
            type=EventType.TOOL_CALL,
            data={"name": "test"}
        )
        
        data = event.to_dict()
        assert data["type"] == "tool_call"
        assert data["data"] == {"name": "test"}
    
    def test_event_from_dict(self):
        """Test event from dictionary creation."""
        data = {
            "type": "content",
            "data": {"message": "test"},
            "timestamp": 1234567890.0
        }
        
        event = Event.from_dict(data)
        assert event.type == EventType.CONTENT
        assert event.data == {"message": "test"}


class TestAgent:
    """Test agent."""
    
    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return Config()
    
    @pytest.fixture
    def agent(self, config):
        """Create test agent."""
        return Agent(config)
    
    def test_agent_creation(self, agent):
        """Test agent creation."""
        assert agent.agent_id is not None
        assert agent.session is not None
        assert len(agent.tools) > 0
    
    def test_agent_has_builtin_tools(self, agent):
        """Test agent has builtin tools."""
        assert "read_file" in agent.tools
        assert "write_file" in agent.tools
        assert "execute_bash" in agent.tools
    
    def test_prepare_messages(self, agent):
        """Test preparing messages for LLM."""
        agent.session.add_message("user", "Hello")
        messages = agent._prepare_messages()
        
        assert len(messages) >= 2
        assert messages[0].role == "system"
        assert messages[-1].role == "user"
    
    def test_prepare_tools(self, agent):
        """Test preparing tools for LLM."""
        tools = agent._prepare_tools()
        
        assert len(tools) > 0
        for tool in tools:
            assert tool["type"] == "function"
            assert "function" in tool
    
    def test_agent_reset(self, agent):
        """Test agent reset."""
        agent.session.add_message("user", "Test")
        agent.reset()
        
        assert len(agent.session.messages) == 0
    
    def test_save_load_state(self, agent):
        """Test saving and loading state."""
        agent.session.add_message("user", "Test message")
        
        state = agent.save_state()
        assert state["agent_id"] == agent.agent_id
        
        # Create new agent and load state
        new_agent = Agent(agent.config)
        new_agent.load_state(state)
        assert new_agent.agent_id == agent.agent_id


@pytest.mark.asyncio
class TestAgentAsync:
    """Test async agent functionality."""
    
    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return Config()
    
    @pytest.fixture
    def agent(self, config):
        """Create test agent."""
        return Agent(config)
    
    async def test_agent_run(self, agent):
        """Test agent run method."""
        events = []
        
        async for event in agent.run("Hello"):
            events.append(event)
            assert isinstance(event, Event)
        
        # Should have at least start and end events
        assert len(events) >= 2
        assert events[0].type.value == "start"
        assert events[-1].type.value == "end"
