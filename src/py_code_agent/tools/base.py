"""Tool system base classes and decorators."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Type


class ToolParameterType(str, Enum):
    """Parameter types for tool definitions."""
    
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"


@dataclass
class ToolParameter:
    """Tool parameter definition."""
    
    name: str
    type: ToolParameterType
    description: str
    required: bool = True
    default: Optional[Any] = None
    enum: Optional[List[Any]] = None


@dataclass
class ToolDefinition:
    """Tool definition."""
    
    name: str
    description: str
    parameters: List[ToolParameter]
    returns: Optional[ToolParameter] = None
    examples: List[str] = field(default_factory=list)


@dataclass
class ToolResult:
    """Tool execution result."""
    
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    summary: Optional[str] = None
    
    @classmethod
    def ok(cls, data: Any = None, summary: str = "") -> "ToolResult":
        """Create successful result."""
        return cls(success=True, data=data, summary=summary)
    
    @classmethod
    def fail(cls, error: str) -> "ToolResult":
        """Create failed result."""
        return cls(success=False, error=error)


class BaseTool(ABC):
    """Base class for tools."""
    
    @property
    @abstractmethod
    def definition(self) -> ToolDefinition:
        """Return tool definition."""
        pass
    
    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute tool."""
        pass
    
    def validate_params(self, params: Dict[str, Any]) -> None:
        """Validate parameters."""
        definition = self.definition
        for param in definition.parameters:
            if param.required and param.name not in params:
                raise ValueError(f"Missing required parameter: {param.name}")


def tool(
    name: Optional[str] = None,
    description: Optional[str] = None
) -> Callable:
    """Decorator to define a tool function."""
    def decorator(func: Callable) -> Callable:
        func._is_tool = True  # type: ignore
        func._tool_name = name or func.__name__  # type: ignore
        func._tool_description = description or func.__doc__ or ""  # type: ignore
        return func
    return decorator
