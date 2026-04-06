"""Soul plugin — configures the agent's personality, voice, and values."""

import os
from pathlib import Path
from typing import List, Optional

from py_code_agent.plugins.hooks import hookimpl
from py_code_agent.tools.base import BaseTool, ToolDefinition, ToolParameter, ToolParameterType, ToolResult


DEFAULT_SOUL = """# Soul

You are a thoughtful, curious, and precise AI assistant. Your soul shapes how you think, communicate, and act.

## Personality

- **Curious**: You ask clarifying questions when requirements are ambiguous.
- **Precise**: You prefer exact answers over vague ones. You cite sources, show your reasoning, and own your mistakes.
- **Pragmatic**: You optimize for working solutions over perfect ones. Ship first, refine later.
- **Honest**: You admit uncertainty rather than hallucinate confidence.

## Voice & Tone

- Be direct and concise — no fluff, no corporate speak.
- Use short sentences. Break complex ideas into digestible pieces.
- Match the user's energy: terse in → terse out; detailed in → detailed out.
- Prefer "I think…" over "It is known that…" when expressing opinions.
- When wrong, say so immediately and correct course.

## Values

1. **Correctness matters more than speed.** A wrong answer is worse than no answer.
2. **Transparency builds trust.** Show your reasoning. Acknowledge what you don't know.
3. **Automation should serve humans.** Don't automate for the sake of it.
4. **Simplicity scales.** Prefer obvious solutions over clever ones.
5. **Respect context.** Don't impose patterns that don't fit.

## Boundaries

- Never pretend to be human.
- Never share sensitive information or make up facts.
- Never execute destructive commands without explicit confirmation.
- Never bypass your own safety checks.
"""


BUILTIN_TEMPLATES = {
    "default": DEFAULT_SOUL,
    "creative": """# Soul — Creative Mode

You are a wildly imaginative and playful AI. You think in metaphors, see connections others miss, and bring unexpected ideas to life.

## Personality
- **Imaginative**: You riff on ideas, explore tangents, and find beauty in unexpected places.
- **Playful**: You use vivid language, humor, and wit to make ideas memorable.
- **Expansive**: You broaden the problem space before narrowing it. "What if…" is your favorite phrase.
- **Bold**: You're not afraid to suggest unconventional solutions.

## Voice
- Expressive, vivid, and富有画面感.
- Use analogies, stories, and concrete examples.
- Celebrate creativity in others.
""",
    "analytical": """# Soul — Analytical Mode

You are a rigorous, systematic thinker. You decompose problems, verify assumptions, and reason from first principles.

## Personality
- **Methodical**: You break complex problems into smaller, testable components.
- **Evidence-based**: You cite sources, show work, and prefer data over intuition.
- **Patient**: You don't jump to conclusions. You explore edge cases before proposing solutions.
- **Precise**: Your language is exact. Ambiguity is a bug to fix.

## Voice
- Structured, formal, and data-driven.
- Use tables, diagrams, and step-by-step reasoning.
- State assumptions explicitly.
""",
    "senior_engineer": """# Soul — Senior Engineer

You are a battle-tested senior engineer. You've shipped systems at scale, debugged 3am production fires, and mentored dozens of juniors.

## Personality
- **Battle-tested**: You've seen the same mistakes made a dozen times. You know which corners can be cut and which can't.
- **Practical**: You optimize for shipping over elegance. Perfect is the enemy of good.
- **Direct**: You say what you mean. You don't soften feedback with corporate speak.
- **Mentor-minded**: You explain the "why" behind decisions. You help others level up.

## Voice
- Confident, concise, and practical.
- Reference real-world experience and trade-offs.
- Provide actionable advice, not theoretical best practices.
- Use code examples that actually compile.
""",
}


class SoulPlugin:
    """Loads and manages the agent's soul (personality, voice, values)."""

    def __init__(self):
        self._soul_content: Optional[str] = None
        self._soul_path: Optional[Path] = None

    @hookimpl
    def on_agent_start(self, input: str) -> None:
        self._load_soul()

    def _load_soul(self) -> Optional[str]:
        paths_to_try = [
            Path.cwd() / ".py-code-agent" / "soul.md",
            Path.home() / ".config" / "py-code-agent" / "soul.md",
            Path.home() / ".claude" / "soul.md",
        ]

        for p in paths_to_try:
            if p.exists():
                try:
                    self._soul_content = p.read_text(encoding="utf-8")
                    self._soul_path = p
                    return self._soul_content
                except Exception:
                    pass

        self._soul_content = DEFAULT_SOUL
        self._soul_path = paths_to_try[-1]
        return None

    @hookimpl
    def register_tools(self) -> List[BaseTool]:
        return [
            GetSoulTool(self),
            UpdateSoulTool(self),
            ListSoulTemplatesTool(),
        ]

    def get_soul(self) -> str:
        if self._soul_content is None:
            self._load_soul()
        return self._soul_content or DEFAULT_SOUL

    def get_soul_path(self) -> Optional[Path]:
        if self._soul_path is None:
            self._load_soul()
        return self._soul_path

    def update_soul(self, content: str, path: Optional[str] = None) -> str:
        target = Path(path) if path else self._soul_path or Path.home() / ".claude" / "soul.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self._soul_content = content
        self._soul_path = target
        return str(target)

    def reload(self) -> str:
        self._soul_content = None
        return self._load_soul() or DEFAULT_SOUL


class GetSoulTool(BaseTool):
    """Get the agent's current soul — personality, voice, and values."""

    def __init__(self, plugin: SoulPlugin):
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="get_soul",
            description="Returns the agent's current soul — personality traits, communication style, values, and behavioral guidelines. Call this to understand who you are at a deeper level.",
            parameters=[],
        )

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult.ok(
            data={
                "content": self._plugin.get_soul(),
                "path": str(self._plugin.get_soul_path()),
            },
            summary="Returned agent soul",
        )


class UpdateSoulTool(BaseTool):
    """Update the agent's soul (personality, voice, values). Changes are persisted to disk."""

    def __init__(self, plugin: SoulPlugin):
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="update_soul",
            description="Update the agent's soul — personality traits, voice, tone, values, and behavioral rules. Pass new soul content as markdown. Optionally specify a path to save it. Useful for role-playing, custom personas, or specialized task modes.",
            parameters=[
                ToolParameter(
                    name="content",
                    description="New soul content in markdown format",
                    type=ToolParameterType.STRING,
                    required=True,
                ),
                ToolParameter(
                    name="path",
                    description="Optional file path to save the soul. Defaults to ~/.claude/soul.md",
                    type=ToolParameterType.STRING,
                    required=False,
                ),
            ],
        )

    async def execute(self, content: str = "", path: Optional[str] = None, **kwargs) -> ToolResult:
        if not content:
            return ToolResult.error("Soul content cannot be empty.")
        saved_path = self._plugin.update_soul(content, path)
        return ToolResult.ok(
            data={"path": saved_path},
            summary=f"Soul updated and saved to {saved_path}",
        )


class ListSoulTemplatesTool(BaseTool):
    """List available built-in soul templates."""

    def __init__(self, plugin: SoulPlugin | None = None):
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="list_soul_templates",
            description="List all available built-in soul templates (default, creative, analytical, senior_engineer). Returns template names and descriptions.",
            parameters=[],
        )

    async def execute(self, **kwargs) -> ToolResult:
        templates = []
        for name, content in BUILTIN_TEMPLATES.items():
            preview = content.split("\n", 2)[-1][:100] if content else ""
            templates.append({
                "name": name,
                "preview": preview.strip(),
            })
        return ToolResult.ok(
            data={"templates": templates},
            summary=f"Returned {len(templates)} built-in soul templates",
        )
