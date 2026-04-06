"""LLM Provider using LiteLLM."""

from typing import Any, AsyncIterator, Dict, List, Optional

from py_code_agent.core.events import Event, EventType


class MessageRole:
    """Message roles."""
    
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Message:
    """Message class."""
    
    def __init__(
        self,
        role: str,
        content: str,
        name: Optional[str] = None,
        tool_calls: Optional[List[Dict]] = None,
        tool_call_id: Optional[str] = None
    ):
        self.role = role
        self.content = content
        self.name = name
        self.tool_calls = tool_calls
        self.tool_call_id = tool_call_id
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data: Dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name:
            data["name"] = self.name
        if self.tool_calls:
            data["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            data["tool_call_id"] = self.tool_call_id
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        """Create from dictionary."""
        return cls(
            role=data["role"],
            content=data["content"],
            name=data.get("name"),
            tool_calls=data.get("tool_calls"),
            tool_call_id=data.get("tool_call_id")
        )


class LiteLLMProvider:
    """LiteLLM provider for unified LLM access."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.model = config.get("model", "gpt-4")
        self.api_key = config.get("api_key")
        self.base_url = config.get("base_url")
        self.timeout = config.get("timeout", 60)
        self.max_retries = config.get("max_retries", 3)
        self.max_tokens = config.get("max_tokens")

        self._setup_litellm()

    def _setup_litellm(self) -> None:
        """Configure LiteLLM (lazy import to avoid 30s overhead at import time)."""
        import litellm  # noqa: E402
        if self.api_key:
            litellm.api_key = self.api_key
        
        if self.base_url:
            litellm.api_base = self.base_url
        
        litellm.request_timeout = self.timeout
        litellm.num_retries = self.max_retries
        litellm.set_verbose = self.config.get("verbose", False)
        
        # Debug mode - use `litellm._turn_on_debug()` for detailed logging
        if self.config.get("debug", False):
            litellm._turn_on_debug()
        
        if self.config.get("callbacks"):
            litellm.callbacks = self.config["callbacks"]
    
    async def complete(
        self,
        messages: List[Message],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """Complete request (non-streaming)."""
        from litellm import acompletion  # noqa: E402
        try:
            litellm_messages = [m.to_dict() for m in messages]
            
            response = await acompletion(
                model=self.model,
                messages=litellm_messages,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=self.timeout,
                api_key=self.api_key,
                base_url=self.base_url,
                **kwargs
            )
            
            choice = response.choices[0]
            message = choice.message
            
            tool_calls = None
            if hasattr(message, 'tool_calls') and message.tool_calls:
                tool_calls = [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in message.tool_calls
                ]
            
            usage = None
            if hasattr(response, 'usage') and response.usage:
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                }
            
            return {
                "content": message.content or "",
                "tool_calls": tool_calls,
                "usage": usage,
                "model": response.model,
                "finish_reason": choice.finish_reason
            }
            
        except Exception as e:
            raise Exception(f"LLM completion failed: {str(e)}")
    
    async def stream(
        self,
        messages: List[Message],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> AsyncIterator[Event]:
        """Stream request."""
        from litellm import acompletion  # noqa: E402
        try:
            litellm_messages = [m.to_dict() for m in messages]

            response = await acompletion(
                model=self.model,
                messages=litellm_messages,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=self.timeout,
                api_key=self.api_key,
                base_url=self.base_url,
                stream=True,
                **kwargs
            )

            tool_buf: Dict[int, Dict[str, Any]] = {}

            async for chunk in response:
                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta
                finish_reason = chunk.choices[0].finish_reason

                if hasattr(delta, 'content') and delta.content:
                    yield Event(
                        type=EventType.CONTENT,
                        data={"content": delta.content}
                    )

                if hasattr(delta, 'tool_calls') and delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_buf:
                            tool_buf[idx] = {"id": None, "name": None, "arguments": ""}
                        if tc.id:
                            tool_buf[idx]["id"] = tc.id
                        if tc.function and tc.function.name:
                            tool_buf[idx]["name"] = tc.function.name
                        if tc.function and tc.function.arguments:
                            tool_buf[idx]["arguments"] += tc.function.arguments

                if finish_reason:
                    for buf in tool_buf.values():
                        if buf["name"] and buf["arguments"]:
                            yield Event(
                                type=EventType.TOOL_CALL,
                                data={"name": buf["name"], "arguments": buf["arguments"]}
                            )
                    tool_buf.clear()
                    yield Event(
                        type=EventType.END,
                        data={"finish_reason": finish_reason}
                    )

        except Exception as e:
            yield Event(
                type=EventType.ERROR,
                data={"error": str(e)}
            )
