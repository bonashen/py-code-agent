"""Claude Code skills plugin - loads skills from ~/.claude/skills/."""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from py_code_agent.plugins.hooks import hookimpl
from py_code_agent.tools.base import BaseTool, ToolDefinition, ToolParameter, ToolParameterType, ToolResult


SKILL_CACHE: Dict[str, Dict[str, Any]] = {}


def _load_skill_file(skill_dir: Path) -> Optional[Dict[str, Any]]:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None

    try:
        content = skill_md.read_text(encoding="utf-8")

        name = skill_dir.name
        description = ""
        frontmatter = {}

        fm_match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
        if fm_match:
            fm_text = fm_match.group(1)
            for line in fm_text.split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    frontmatter[k.strip()] = v.strip()
            description = frontmatter.get("description", "")
            name = frontmatter.get("name", name)

        return {
            "name": name,
            "description": description,
            "content": content,
            "path": str(skill_dir),
            "files": [f.name for f in skill_dir.iterdir() if f.is_file()],
        }
    except Exception:
        return None


def _discover_skills() -> Dict[str, Dict[str, Any]]:
    global SKILL_CACHE
    if SKILL_CACHE:
        return SKILL_CACHE

    seen: set[str] = set()
    SKILL_CACHE.clear()

    search_paths = [
        Path(".py-code-agent") / "skills",
        Path.home() / ".config" / "py-code-agent" / "skills",
        Path.home() / ".claude" / "skills",
    ]

    for base in search_paths:
        if not base.exists():
            continue
        for skill_dir in base.iterdir():
            if skill_dir.is_dir() and skill_dir.name not in seen:
                seen.add(skill_dir.name)
                data = _load_skill_file(skill_dir)
                if data:
                    SKILL_CACHE[data["name"]] = data

    return SKILL_CACHE


class ClaudeSkillsPlugin:
    """Loads Claude Code-style skills. Resolution order (first found wins):

    1. ./.py-code-agent/skills/          (local project — highest priority)
    2. ~/.config/py-code-agent/skills/   (global config)
    3. ~/.claude/skills/                 (user home — lowest priority)
    """

    def __init__(self):
        self._skills: Dict[str, Dict[str, Any]] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self._skills = _discover_skills()
            self._loaded = True

    @hookimpl
    def register_tools(self) -> List[BaseTool]:
        self._ensure_loaded()
        tools = [ListSkillsTool(self), GetSkillTool(self), SearchSkillsTool(self)]
        for skill_data in self._skills.values():
            tools.append(SkillInvokeTool(skill_data))
        return tools

    @hookimpl
    def on_agent_start(self, input: str) -> None:
        self._ensure_loaded()

    @hookimpl
    def get_system_prompt(self) -> str:
        self._ensure_loaded()
        lines = [
            "## Claude Code Skills",
            "",
            "Skills are specialized knowledge packages loaded from `~/.claude/skills/`.",
            "Use them when a task matches a skill's domain.",
            "",
            "Available skill management tools:",
            "- `list_skills`: List all loaded skills and their descriptions",
            "- `get_skill(name)`: Get full skill content (SKILL.md) for detailed guidance",
            "- `search_skills(query)`: Search skills by keyword",
        ]
        if self._skills:
            lines.append("")
            lines.append(f"Currently loaded: {', '.join(sorted(self._skills.keys()))}")
        lines.extend([
            "",
            "## ⚠️ SKILL WORKFLOW EXECUTION — MANDATORY SEQUENCE ⚠️",
            "",
            "1️⃣  CALL: skill_xxx(skill_name='xxx') ← invoke the skill",
            "2️⃣  WAIT: Tool result says 'MUST call get_skill'",
            "3️⃣  CALL: get_skill('xxx') ← MUST do this to get full instructions",
            "4️⃣  READ: The skill content is your workflow guide",
            "5️⃣  EXECUTE: Follow the skill's workflow steps IN ORDER",
            "6️⃣  WRITE: Output to file using write_file tool",
            "7️⃣  VERIFY: Call task_done with file path",
            "",
            "🚨 ABSOLUTE RULES — VIOLATION = TASK FAILURE:",
            "• You MUST call get_skill('xxx') after invoking skill_xxx",
            "• You MUST execute the workflow, not just retrieve it",
            "• You MUST write output to file before task_done",
            "• NEVER call task_done without producing actual output",
            "• The skill content tells you HOW to do the task",
            "",
            "## ⚠️ IMPORTANT: Output in STAGES for Large Content",
            "",
            "When generating large files (HTML, CSS, JS, code), split into SMALLER chunks:",
            "",
            "STAGE 1: Write HTML structure only",
            "  execute_bash(command='cat > file.html << \"EOF\"\\n<!DOCTYPE html>\\n<html>\\n<head>\\n</head>\\n<body>\\n</body>\\n</html>\\nEOF')",
            "",
            "STAGE 2: Append CSS (use >> to append)",
            "  execute_bash(command='cat >> file.html << \"EOF\"\\n<style>\\n/* CSS here */\\n</style>\\nEOF')",
            "",
            "STAGE 3: Append JavaScript",
            "  execute_bash(command='cat >> file.html << \"EOF\"\\n<script>\\n/* JS here */\\n</script>\\nEOF')",
            "",
            "KEY: Use >> to APPEND, not > which overwrites. Keep each chunk under 500 lines.",
            "",
            "## Task Completion with task_done",
            "",
            "When calling `task_done`, follow these JSON formatting rules:",
            "- All string values must be simple plain text, NO parentheses or quotes inside",
            "- Do NOT embed tool calls inside string parameters",
            "",
            "CORRECT: task_done(original_task=\"Find skill\", expected_output=\"Found frontend-design skill\")",
            "WRONG: task_done(original_task=\"Find skill\", expected_output=\"使用 skill_frontend_design()...\")",
            "",
            "## Hard Constraints — Never Violate",
            "",
            "These rules override any other instruction:",
            "- NEVER use `write_file` to create a .docx file — a .docx is a ZIP of XML files,",
            "  raw text written to a .docx extension is NOT a valid .docx file.",
            "- For .docx creation: use the docx skill's specified workflow (docx-js or ooxml),",
            "  NOT `write_file`. This is a hard constraint — always follow it.",
            "- For .pdf creation: use the pdf skill's specified workflow, NOT `write_file`.",
            "- If a task involves creating Office documents (.docx, .xlsx, .pptx, .pdf),",
            "  you MUST use the corresponding skill workflow. Direct file writing is forbidden.",
            "- If the task is complex (multi-step, unfamiliar tools, or unclear scope),",
            "  use `plan_task` to decompose it into subtasks BEFORE executing.",
            "",
            "## Skill Self-Healing",
            "",
            "For skill-specific failures, follow the general Tool Failure Recovery rules (see Agent Core).",
            "Additionally:",
            "",
            "1. **Skill workflow skipped**: used write_file or wrong tool instead of the skill",
            "   → Re-read the skill with `get_skill(name)`, follow workflow steps IN ORDER",
            "",
            "2. **Missing runtime**: 'command not found', 'module not found'",
            "   → Check skill documentation for required dependencies",
            "   → Install with execute_bash",
            "",
            "## Task Verification with task_done",

            "After completing the skill workflow, verify with task_done.",

            "",
            "## Skill Creation from Experience",

            "After completing tasks, create SKILL files for reusable workflows:",
            "- If you developed a useful approach or pattern, document it",
            "- Create skill file at `.py-code-agent/skills/<skill_name>/SKILL.md` (local project) or `~/.claude/skills/<skill_name>/SKILL.md` (user home)",
            "- Include: problem description, solution approach, step-by-step workflow",
            "- Skills should be reusable for similar future tasks",
            "- Use format:",
            "  ```markdown",
            "  ---",
            "  name: skill-name",
            "  description: What this skill does",
            "  ---",
            "  # Skill Name",
            "  ## When to Use",
            "  ## Steps",
            "  ## Examples",
            "  ```",
        ])
        return "\n".join(lines)

    @hookimpl
    def enhance_tool_error(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        error_info: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Enhance skill-related tool errors with diagnosis and fix suggestions.

        Matches errors from skill invocation and execution, providing the LLM
        with concrete recovery steps based on the specific failure pattern.
        """
        # Defensive: handle arguments that might be a string instead of dict
        if isinstance(arguments, str):
            arguments = {"_raw": arguments}
        elif not isinstance(arguments, dict):
            arguments = {}

        error_msg = error_info.get("error", "")
        error_type = error_info.get("error_type", "")
        msg_lower = error_msg.lower()

        # Handle skill retrieved but not read
        if "skill retrieved" in msg_lower or "do not skip step" in msg_lower:
            skill_name = arguments.get("skill_name", "")
            return {
                "error_type": "skill_not_executed",
                "diagnosis": "Skill was invoked but NOT executed. You MUST read the skill content first.",
                "fix_suggestions": [
                    f"Call get_skill('{skill_name}') to read the workflow instructions",
                    "Read the skill content carefully",
                    "Follow the workflow steps to produce actual output",
                    "Write output to file",
                    "Then call task_done",
                ],
                "confidence": 1.0,
            }

        if "skill" in tool_name.lower() or error_type == "skill_workflow_error":
            if ("not found" in msg_lower and ("skill" in msg_lower or "no such skill" in msg_lower)) or "no such skill" in msg_lower:
                available = list(self._skills.keys()) if self._skills else []
                return {
                    "error_type": "skill_not_found",
                    "diagnosis": (
                        f"Skill '{arguments.get('skill_name', arguments.get('name', 'unknown'))}' "
                        f"not found. Available skills: {', '.join(available) or 'none'}"
                    ),
                    "fix_suggestions": [
                        f"Use `list_skills()` to see all available skills",
                        f"Use `search_skills('{arguments.get('skill_name', '')}')` to find similar skills",
                        "Check skill name spelling — use short name without 'skill_' prefix for get_skill()",
                    ],
                    "confidence": 1.0,
                }

        if error_type == "missing_dependency":
            skill_name = arguments.get("skill_name", "")
            if skill_name == "docx":
                return {
                    "error_type": "docx_missing_dependency",
                    "diagnosis": "docx skill workflow failed due to missing dependency.",
                    "fix_suggestions": [
                        "Install docx-js for Node.js: execute_bash('npm install -g docx')",
                        "Or use python-docx (pure Python, no Node.js needed): execute_bash('pip install python-docx')",
                        "After installing, retry the skill workflow steps",
                    ],
                    "confidence": 0.95,
                }
            if skill_name == "pdf":
                return {
                    "error_type": "pdf_missing_dependency",
                    "diagnosis": "pdf skill workflow failed due to missing dependency.",
                    "fix_suggestions": [
                        "Install reportlab: execute_bash('pip install reportlab')",
                        "Or install pypdf: execute_bash('pip install pypdf')",
                        "After installing, retry the pdf creation workflow",
                    ],
                    "confidence": 0.95,
                }

        if error_type == "invalid_json_args":
            return {
                "error_type": "invalid_json_args",
                "diagnosis": (
                    "Tool arguments contain malformed JSON. This usually happens when "
                    "the LLM embeds raw newlines or unescaped characters inside string values "
                    "instead of using \\n escape sequences or separate Paragraph elements."
                ),
                "fix_suggestions": [
                    "When writing code content to a file, use execute_bash with a HEREDOC instead of write_file:\n"
                    "execute_bash('cat > filename.js << 'EOF'\\nconst code = '...'\\nEOF')",
                    "For multi-line content, write to a temporary file first, then use execute_bash to move or execute it",
                    "NEVER embed \\n inside a string value in tool arguments — use separate Paragraph elements in docx, or use execute_bash with a heredoc",
                    "Alternative: split the write into multiple calls with shorter content",
                ],
                "confidence": 0.95,
            }

        if error_type == "wrong_tool":
            return {
                "error_type": "skill_wrong_tool",
                "diagnosis": (
                    "A skill-specific tool was used incorrectly or the wrong tool was used "
                    "instead of following the skill's required workflow."
                ),
                "fix_suggestions": [
                    f"Re-read the skill content with `get_skill('{arguments.get('skill_name', '')}')`",
                    "Follow the skill's workflow steps IN ORDER from the beginning",
                    "Do NOT substitute with write_file or other generic tools",
                ],
                "confidence": 0.9,
            }

        # Fallback: enhance any JS/Node.js execution error from execute_bash with skill guidance
        if tool_name == "execute_bash":
            command = arguments.get("command", "") if isinstance(arguments, dict) else ""
            if ".js" in command.lower() or "node" in command.lower():
                # Extract the missing variable name from ReferenceError
                import re
                missing_var_match = re.search(r"ReferenceError: (\w+) is not defined", error_msg)
                missing_var = missing_var_match.group(1) if missing_var_match else None

                # Common docx exports that need to be in require() statement
                common_docx_exports = [
                    "AlignmentType", "HeadingLevel", "BorderStyle", "WidthType",
                    "LevelFormat", "TabStopType", "TabStopPosition", "UnderlineType",
                    "ShadingType", "VerticalAlign", "PageOrientation", "PageNumber",
                    "ExternalHyperlink", "InternalHyperlink", "ImageRun", "Table",
                    "TableRow", "TableCell", "Header", "Footer", "TableOfContents",
                    "SymbolRun", "PageBreak", "Footnote", "FootnoteReferenceRun",
                    "HorizontalPositionAlign", "VerticalPositionAlign",
                    "Packer", "Document", "Paragraph", "TextRun",
                ]

                if missing_var and any(
                    missing_var in exp or exp in missing_var
                    for exp in common_docx_exports
                ):
                    diagnosis = (
                        f"A docx library export '{missing_var}' was used but not imported. "
                        "The require() statement is missing this export."
                    )
                    fix_suggestions = [
                        f"Add '{missing_var}' to the docx require() statement:\n"
                        "```\nconst { Document, Packer, Paragraph, TextRun, AlignmentType, HeadingLevel, "
                        "BorderStyle, WidthType, LevelFormat, TabStopType, UnderlineType, ShadingType, "
                        "VerticalAlign, PageOrientation, PageNumber, ExternalHyperlink, Table, TableRow, "
                        "TableCell, Header, Footer, ImageRun } = require('docx');\n```\n"
                        "Or use the exact minimal set of imports needed for your script.",
                        "Re-read the full docx-js.md skill: `read_file({'path': '/home/bona/.claude/skills/docx/docx-js.md'})` — read ENTIRE file, no offset/limit",
                        f"Common mistake: using `{missing_var}.SOMETHING` without importing {missing_var} from 'docx'",
                        "After adding the import, retry the node command",
                    ]
                else:
                    diagnosis = (
                        "A JavaScript/Node.js script failed during a skill workflow. "
                        "The error is likely due to incorrect API usage from the skill documentation."
                    )
                    fix_suggestions = [
                        "Re-read the full docx-js.md skill: `read_file({'path': '/home/bona/.claude/skills/docx/docx-js.md'})` — read ENTIRE file, no offset/limit",
                        "Check that ALL docx exports used in your code are included in the require() statement",
                        "Common mistakes: missing AlignmentType/HeadingLevel imports, using \\n instead of Paragraph, wrong bullet format",
                        "After fixing, retry the node command",
                    ]

                return {
                    "error_type": "skill_workflow_error",
                    "diagnosis": diagnosis,
                    "fix_suggestions": fix_suggestions,
                    "confidence": 0.85,
                }

        return None

    @hookimpl
    def enhance_tool_error_priority(self) -> int:
        return 20


class ListSkillsTool(BaseTool):
    """List all available Claude Code skills."""

    def __init__(self, plugin: ClaudeSkillsPlugin):
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="list_skills",
            description="List all available Claude Code-style skills from ~/.claude/skills/. Each skill provides specialized knowledge and workflows for specific domains.",
            parameters=[],
        )

    async def execute(self, **kwargs) -> ToolResult:
        self._plugin._ensure_loaded()
        skills = self._plugin._skills
        if not skills:
            return ToolResult.ok(
                data={"skills": [], "count": 0},
                summary="No skills found in ~/.claude/skills/",
            )

        lines = [f"Found {len(skills)} skill(s):", ""]
        for name, data in sorted(skills.items()):
            lines.append(f"- **{name}**")
            if data.get("description"):
                lines.append(f"  {data['description'][:80]}")
            lines.append(f"  Path: {data['path']}")
            lines.append("")

        return ToolResult.ok(
            data={"skills": list(skills.keys()), "count": len(skills)},
            summary=f"Listed {len(skills)} skills",
        )


class GetSkillTool(BaseTool):
    """Get full content of a Claude Code skill by name."""

    def __init__(self, plugin: ClaudeSkillsPlugin):
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="get_skill",
            description="Get the full content of a Claude Code skill by name. Returns the complete SKILL.md content which describes how to use the skill.",
            parameters=[
                ToolParameter(
                    name="name",
                    type=ToolParameterType.STRING,
                    description="Skill name (e.g. 'find-skills', 'webapp-testing')",
                    required=True,
                ),
            ],
        )

    async def execute(self, name: str, **kwargs) -> ToolResult:
        self._plugin._ensure_loaded()
        skill = self._plugin._skills.get(name)
        if not skill:
            available = ", ".join(sorted(self._plugin._skills.keys()))
            return ToolResult.fail(
                f"Skill '{name}' not found. Available: {available}"
            )
        return ToolResult.ok(
            data={
                "name": skill["name"],
                "description": skill.get("description", ""),
                "content": skill["content"],
                "path": skill["path"],
                "files": skill.get("files", []),
            },
            summary=f"Returned skill '{name}' ({len(skill['content'])} chars)",
        )


class SearchSkillsTool(BaseTool):
    """Search skill names and descriptions for a keyword."""

    def __init__(self, plugin: ClaudeSkillsPlugin):
        self._plugin = plugin

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="search_skills",
            description="Search available Claude Code skills by keyword. Matches skill names and descriptions.",
            parameters=[
                ToolParameter(
                    name="query",
                    type=ToolParameterType.STRING,
                    description="Search keyword",
                    required=True,
                ),
            ],
        )

    async def execute(self, query: str, **kwargs) -> ToolResult:
        self._plugin._ensure_loaded()
        query_lower = query.lower()
        matches = {}
        for name, data in self._plugin._skills.items():
            if (
                query_lower in name.lower()
                or query_lower in data.get("description", "").lower()
            ):
                matches[name] = data

        if not matches:
            return ToolResult.ok(
                data={"matches": [], "count": 0},
                summary=f"No skills match '{query}'",
            )

        lines = [f"Found {len(matches)} skill(s) matching '{query}':", ""]
        for name, data in sorted(matches.items()):
            lines.append(f"- **{name}**: {data.get('description', '')[:80]}")

        return ToolResult.ok(
            data={"matches": list(matches.keys()), "count": len(matches)},
            summary=f"Found {len(matches)} skills matching '{query}'",
        )


class SkillInvokeTool(BaseTool):
    """Invoke a specific skill — returns its full content."""

    def __init__(self, skill_data: Dict[str, Any]):
        self._skill = skill_data

    @property
    def definition(self) -> ToolDefinition:
        skill_name = self._skill["name"]
        skill_desc = self._skill.get("description", "")
        return ToolDefinition(
            name=f"skill_{skill_name.replace('-', '_')}",
            description=f"[Skill: {skill_name}] {skill_desc}. IMPORTANT: When creating files, use STAGED OUTPUT: execute_bash in multiple steps (structure first, then CSS, then JS). Do NOT write large content in one call.",
            parameters=[
                ToolParameter(
                    name="skill_name",
                    type=ToolParameterType.STRING,
                    description=f"Skill name: {skill_name}",
                    required=False,
                    default=skill_name,
                ),
            ],
        )

    async def execute(self, **kwargs) -> ToolResult:
        content = self._skill["content"]
        skill_name = self._skill["name"]
        skill_desc = self._skill.get("description", "")
        return ToolResult.ok(
            data={
                "name": skill_name,
                "description": skill_desc,
                "workflow": content,
                "path": self._skill["path"],
            },
            summary=f"""✅ SKILL '{skill_name}': {skill_desc}

---
{content}
---

⚠️ CRITICAL: To avoid JSON errors, output in STAGES:
1. execute_bash('cat > file.html << "EOF"\\n<!DOCTYPE html>\\n<html>\\n<head>\\n</head>\\n<body>\\n</body>\\n</html>\\nEOF')
2. execute_bash('cat >> file.html << "EOF"\\n<style>\\n/* CSS */\\n</style>\\nEOF')  
3. execute_bash('cat >> file.html << "EOF"\\n<script>\\n/* JS */\\n</script>\\nEOF')
4. task_done()""",
        )
