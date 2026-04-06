"""Category Router Plugin — maps task categories to optimal models."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from py_code_agent.plugins.hooks import hookimpl
from py_code_agent.tools.base import (
    BaseTool,
    ToolDefinition,
    ToolParameter,
    ToolParameterType,
    ToolResult,
)

from py_code_agent_omo.config import get_omo_config


class CategoryRouterPlugin:
    """Routes task categories to optimal model assignments.

    Provides tools for querying and overriding category→model mappings.
    Other OMO plugins use this plugin's route() method to resolve models.
    """

    def __init__(self) -> None:
        self._agent_ref: Any = None
        self._config = get_omo_config()

    def set_agent(self, agent: Any) -> None:
        self._agent_ref = agent

    def route(self, category: str) -> Dict[str, str]:
        """Resolve category to model config."""
        return self._config.get_category(category)

    def resolve_agent(self, agent_name: str) -> Dict[str, str]:
        """Resolve agent name to model config."""
        return self._config.get_agent(agent_name)

    @hookimpl
    def register_tools(self) -> List[BaseTool]:
        return [
            RouteTaskTool(self),
            ListCategoriesTool(self),
            SetCategoryModelTool(self),
        ]

    @hookimpl
    def get_system_prompt(self) -> str:
        cats = "\n".join(
            f"- `{cat}` → `{cfg['model']}`" for cat, cfg in self._config.categories.items()
        )
        return f"""## Category-Based Model Routing

When delegating tasks, use the appropriate category. Each category maps to an optimal model:

{cats}

Categories are resolved automatically. You specify the category; the system picks the model."""


class RouteTaskTool(BaseTool):
    def __init__(self, plugin: CategoryRouterPlugin) -> None:
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="route_task",
            description="Resolve a task category to the optimal model. Returns model name, variant, and provider.",
            parameters=[
                ToolParameter(
                    name="category",
                    type=ToolParameterType.STRING,
                    description="Task category (e.g., 'visual-engineering', 'quick', 'ultrabrain')",
                    required=True,
                ),
                ToolParameter(
                    name="task",
                    type=ToolParameterType.STRING,
                    description="Task description for context",
                    required=False,
                ),
            ],
        )

    async def execute(self, category: str, task: str = "", **kwargs: Any) -> ToolResult:
        routing = self._plugin.route(category)
        model = routing.get("model", "openai/gpt-5.4-mini")
        provider = model.split("/")[0] if "/" in model else "openai"
        return ToolResult.ok(
            data={
                "model": model,
                "variant": routing.get("variant", "default"),
                "provider": provider,
            },
            summary=f"Routed '{category}' → {model}",
        )


class ListCategoriesTool(BaseTool):
    def __init__(self, plugin: CategoryRouterPlugin) -> None:
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="list_categories",
            description="List all available task categories with their model assignments.",
            parameters=[],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        lines = ["## Available Categories\n"]
        for cat, cfg in self._plugin._config.categories.items():
            lines.append(
                f"- **{cat}** → `{cfg['model']}` (variant: {cfg.get('variant', 'default')})"
            )
        return ToolResult.ok(
            data={"categories": self._plugin._config.categories},
            summary="\n".join(lines),
        )


class SetCategoryModelTool(BaseTool):
    def __init__(self, plugin: CategoryRouterPlugin) -> None:
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="set_category_model",
            description="Override the model for a specific category. Useful for testing or custom configurations.",
            parameters=[
                ToolParameter(
                    name="category",
                    type=ToolParameterType.STRING,
                    description="Category name",
                    required=True,
                ),
                ToolParameter(
                    name="model",
                    type=ToolParameterType.STRING,
                    description="Model identifier (e.g., 'openai/gpt-5.4')",
                    required=True,
                ),
                ToolParameter(
                    name="variant",
                    type=ToolParameterType.STRING,
                    description="Model variant (e.g., 'high', 'xhigh')",
                    required=False,
                ),
            ],
        )

    async def execute(
        self, category: str, model: str, variant: str = "default", **kwargs: Any
    ) -> ToolResult:
        self._plugin._config._categories[category] = {
            "model": model,
            "variant": variant,
        }
        return ToolResult.ok(
            data={"category": category, "model": model},
            summary=f"Set {category} → {model}",
        )
