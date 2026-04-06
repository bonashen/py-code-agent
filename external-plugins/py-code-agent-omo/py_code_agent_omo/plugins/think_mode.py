"""Think Mode Plugin — structured thinking for complex reasoning."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from py_code_agent.plugins.hooks import hookimpl
from py_code_agent.tools.base import (
    BaseTool,
    ToolDefinition,
    ToolParameter,
    ToolParameterType,
    ToolResult,
)

THINK_PROMPT = """Analyze this problem systematically:

Problem: {problem}

Provide a structured analysis:
1. Understanding: What is the core problem?
2. Constraints: What limitations exist?
3. Options: List 3 possible approaches
4. Tradeoffs: For each option, list pros/cons
5. Recommendation: Which option is best and why?

Return JSON only:
{{
  "understanding": "...",
  "constraints": ["...", "..."],
  "options": [
    {{"name": "...", "pros": ["..."], "cons": ["..."]}}
  ],
  "recommendation": {{"option": "...", "reason": "..."}}
}}"""


class ThinkModePlugin:
    """Provides structured thinking tool for complex problems."""

    def __init__(self) -> None:
        self._agent_ref: Any = None

    def set_agent(self, agent: Any) -> None:
        self._agent_ref = agent

    @hookimpl
    def register_tools(self) -> List[BaseTool]:
        return [UltrathinkTool(self)]

    @hookimpl
    def get_system_prompt(self) -> str:
        return """## Think Mode

For complex problems, use `ultrathink` before acting:
- Architecture decisions
- Multi-system changes
- Security-sensitive modifications
- Performance-critical optimizations

Think mode forces structured reasoning before implementation."""


class UltrathinkTool(BaseTool):
    def __init__(self, plugin: ThinkModePlugin) -> None:
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="ultrathink",
            description="Structured thinking tool for complex problems. Forces analysis of options, tradeoffs, and recommendations before acting.",
            parameters=[
                ToolParameter(
                    name="problem",
                    type=ToolParameterType.STRING,
                    description="The problem to analyze",
                    required=True,
                ),
            ],
        )

    async def execute(self, problem: str, **kwargs: Any) -> ToolResult:
        if not self._plugin._agent_ref:
            return ToolResult.fail("Agent not available")

        try:
            llm = getattr(self._plugin._agent_ref, "llm", None)
            if llm is None:
                return ToolResult.fail("LLM provider not available")

            from py_code_agent.llm.litellm_provider import Message, MessageRole

            messages = [
                Message(role=MessageRole.USER, content=THINK_PROMPT.format(problem=problem))
            ]
            response = llm.complete(messages, temperature=0.3)
            content = response.get("content", "")
            text = content.strip()
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)
            data = json.loads(text)
            rec = data.get("recommendation", {})
            return ToolResult.ok(
                data=data,
                summary=rec.get("reason", "Analysis complete"),
            )
        except json.JSONDecodeError:
            return ToolResult.fail("Could not parse analysis as JSON")
        except Exception as e:
            return ToolResult.fail(f"Think mode failed: {e}")
