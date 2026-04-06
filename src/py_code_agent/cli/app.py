"""CLI App using Textual."""

from typing import Any

from rich.console import Console
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Button, Input, Label, Markdown, Static

console = Console()


class MessageDisplay(Static):
    """Widget to display a message."""
    
    def __init__(self, content: str, is_user: bool = False, **kwargs: Any):
        self.content = content
        self.is_user = is_user
        super().__init__(**kwargs)
    
    def render(self) -> str:
        prefix = "You: " if self.is_user else "Assistant: "
        return f"[bold]{prefix}[/bold]{self.content}"


class AgentApp(App):
    """Textual TUI app for the agent."""
    
    CSS = """
    Screen {
        align: center middle;
    }
    
    #chat-container {
        width: 100%;
        height: 100%;
        padding: 1 2;
    }
    
    #messages {
        width: 100%;
        height: 1fr;
        border: solid green;
        padding: 1;
        overflow-y: scroll;
    }
    
    #input-container {
        width: 100%;
        height: auto;
        margin-top: 1;
    }
    
    #user-input {
        width: 1fr;
    }
    
    #send-button {
        width: auto;
    }
    """
    
    def __init__(self, agent: Any, **kwargs: Any):
        self.agent = agent
        super().__init__(**kwargs)
    
    def compose(self) -> ComposeResult:
        """Compose the UI."""
        with Container(id="chat-container"):
            with Vertical(id="messages"):
                yield Label("Welcome to Py Code Agent! Type your message below.", id="welcome")
            
            with Horizontal(id="input-container"):
                yield Input(placeholder="Type your message...", id="user-input")
                yield Button("Send", id="send-button", variant="primary")
    
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "send-button":
            await self.send_message()
    
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission."""
        if event.input.id == "user-input":
            await self.send_message()
    
    async def send_message(self) -> None:
        """Send user message and get response."""
        input_widget = self.query_one("#user-input", Input)
        messages_widget = self.query_one("#messages", Vertical)
        
        user_input = input_widget.value.strip()
        if not user_input:
            return
        
        # Clear input
        input_widget.value = ""
        
        # Display user message
        messages_widget.mount(Label(f"[bold blue]You:[/bold blue] {user_input}"))
        
        # Get agent response
        try:
            response_text = ""
            async for event in self.agent.run(user_input):
                if event.type.value == "content":
                    content = event.data.get("content", "")
                    response_text += content
            
            if response_text:
                messages_widget.mount(Label(f"[bold green]Assistant:[/bold green] {response_text}"))
            
        except Exception as e:
            messages_widget.mount(Label(f"[bold red]Error:[/bold red] {str(e)}"))
