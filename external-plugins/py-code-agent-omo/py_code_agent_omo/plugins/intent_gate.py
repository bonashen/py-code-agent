"""Intent Gate Plugin — classifies user intent before execution."""

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

INTENT_PROMPT = """Given this user task, classify its intent:

Task: {task}

Categories:
- research: "explain X", "how does Y work" → explore → synthesize → answer
- implementation: "implement X", "add Y", "create Z" → plan → delegate → execute
- investigation: "look into X", "check Y" → explore → report findings
- fix: "X is broken", "error Y" → diagnose → fix minimally
- open-ended: "refactor", "improve" → assess → propose → wait for confirmation

Return JSON only: {{"intent": "...", "confidence": 0.0-1.0, "recommended_action": "..."}}"""


class IntentGatePlugin:
    """Classifies user intent and routes accordingly.

    Stores classification result in ContextPlugin so other OMO plugins
    can read the current intent.
    """

    def __init__(self) -> None:
        self._agent_ref: Any = None
        self._current_intent: Optional[Dict[str, Any]] = None

    def set_agent(self, agent: Any) -> None:
        self._agent_ref = agent

    @hookimpl
    def register_tools(self) -> List[BaseTool]:
        return [ClassifyIntentTool(self)]

    @hookimpl
    def on_agent_start(self, input: str) -> None:
        self._current_intent = self._classify(input)
        self._share_intent()

    @hookimpl
    def get_system_prompt(self) -> str:
        return """## Intent-Aware Execution

Your current task intent has been classified. Follow the recommended approach:
- Research → Explore first, synthesize findings, then answer
- Implementation → Plan before coding, delegate to specialists
- Investigation → Gather evidence, report findings
- Fix → Diagnose root cause, fix minimally
- Open-ended → Assess current state, propose approach, wait for confirmation"""

    def _classify(self, task: str) -> Dict[str, Any]:
        if not self._agent_ref:
            return {
                "intent": "open-ended",
                "confidence": 0.0,
                "recommended_action": "assess first",
            }

        try:
            llm = getattr(self._agent_ref, "llm", None)
            if llm is None:
                return {
                    "intent": "open-ended",
                    "confidence": 0.0,
                    "recommended_action": "assess first",
                }

            from py_code_agent.llm.litellm_provider import Message, MessageRole

            messages = [
                Message(role=MessageRole.USER, content=INTENT_PROMPT.format(task=task[:500]))
            ]
            response = llm.complete(messages, temperature=0.1)
            content = response.get("content", "")
            return self._parse_intent(content)
        except Exception:
            return {"intent": "open-ended", "confidence": 0.0, "recommended_action": "assess first"}

    def _parse_intent(self, content: str) -> Dict[str, Any]:
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            data = json.loads(text)
            if "intent" in data:
                return data
        except (json.JSONDecodeError, TypeError):
            pass
        return {"intent": "open-ended", "confidence": 0.0, "recommended_action": "assess first"}

    def _share_intent(self) -> None:
        if not self._agent_ref or not self._current_intent:
            return
        try:
            pm = getattr(self._agent_ref, "plugin_manager", None)
            if pm is None:
                return
            ctx_plugin = pm.pm.get_plugin("file:context")
            if ctx_plugin and hasattr(ctx_plugin, "write"):
                ctx_plugin.write("current_intent", json.dumps(self._current_intent))
        except Exception:
            pass


class ClassifyIntentTool(BaseTool):
    def __init__(self, plugin: IntentGatePlugin) -> None:
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="classify_intent",
            description="Classify the intent of a task. Returns intent type, confidence, and recommended action.",
            parameters=[
                ToolParameter(
                    name="task",
                    type=ToolParameterType.STRING,
                    description="Task to classify",
                    required=True,
                ),
            ],
        )

    async def execute(self, task: str, **kwargs: Any) -> ToolResult:
        result = self._plugin._classify(task)
        return ToolResult.ok(
            data=result,
            summary=f"Intent: {result['intent']} (confidence: {result.get('confidence', 0)})",
        )
