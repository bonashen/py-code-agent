"""Agent core implementation."""

import json
import logging
import uuid
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from py_code_agent.config.models import Config
from py_code_agent.core.events import Event, EventType
from py_code_agent.core.session import Session
from py_code_agent.llm.litellm_provider import LiteLLMProvider, Message, MessageRole
from py_code_agent.tools.base import ToolResult
from py_code_agent.plugins.manager import PluginManager


class Agent:
    """Main agent class."""
    
    def __init__(self, config: Config):
        """Initialize agent."""
        self.config = config
        self.agent_id = str(uuid.uuid4())
        self.session = Session()
        
        # Initialize LLM provider
        model = config.llm.model
        # Prepend openai/ for OpenAI-compatible base URLs so LiteLLM routes correctly
        if config.llm.base_url and not any(model.startswith(p + "/") for p in ("openai", "azure", "anthropic", "cohere", "ollama", "mistral")):
            model = "openai/" + model

        llm_config = {
            "model": model,
            "api_key": config.llm.api_key,
            "base_url": config.llm.base_url,
            "timeout": config.llm.timeout,
            "max_retries": config.llm.max_retries,
            "max_tokens": config.llm.max_tokens,
        }
        self.llm = LiteLLMProvider(llm_config)
        
        self.tools: Dict[str, Any] = {}
        self._register_builtin_tools()
        self._setup_plugins()
    
    def _register_builtin_tools(self) -> None:
        """Register built-in tools."""
        from py_code_agent.tools.builtin import (
            ExecuteBashTool,
            ReadFileTool,
            TaskDoneTool,
            WriteFileTool,
        )
        
        self.register_tool(ReadFileTool(
            allowed_paths=self.config.tools.allowed_paths,
            blocked_paths=self.config.tools.blocked_paths,
        ))
        self.register_tool(WriteFileTool(
            allowed_paths=self.config.tools.allowed_paths,
            blocked_paths=self.config.tools.blocked_paths,
        ))
        self.register_tool(ExecuteBashTool())
        self.register_tool(TaskDoneTool())
    
    def register_tool(self, tool: Any) -> None:
        """Register a tool."""
        self.tools[tool.definition.name] = tool

    def clone(self, modifications: Optional[Dict[str, Any]] = None) -> "Agent":
        import copy
        
        modifications = modifications or {}
        
        config = copy.deepcopy(self.config)
        new_agent = Agent(config)
        
        disabled_plugins = modifications.get("disabled_plugins", [])
        for name in disabled_plugins:
            try:
                new_agent.plugin_manager.disable_plugin(name)
            except Exception:
                pass
        
        disabled_tools = modifications.get("disabled_tools", [])
        for tool_name in disabled_tools:
            new_agent.tools.pop(tool_name, None)
        
        extra_tools = modifications.get("extra_tools", [])
        for tool in extra_tools:
            new_agent.register_tool(tool)
        
        setattr(new_agent, "_clone_modifications", modifications)
        
        return new_agent
    
    def _setup_plugins(self) -> None:
        from pathlib import Path

        repo_root = Path(__file__).parent.parent.parent.parent

        plugin_dirs = [repo_root / "plugins" / "builtin"]
        local_plugins = Path.cwd() / ".py-code-agent" / "plugins"
        if local_plugins.exists():
            plugin_dirs.append(local_plugins)
        global_plugins = Path.home() / ".config" / "py-code-agent" / "plugins"
        if global_plugins.exists():
            plugin_dirs.append(global_plugins)

        self.plugin_manager = PluginManager(plugin_config=self.config.plugins)
        self.plugin_manager.load_plugins(plugin_dirs)
        from py_code_agent.plugins.manager import PluginPlugin, LoadPluginsTool, PluginHealth
        PluginPlugin.set_plugin_manager(self.plugin_manager)
        plugin_plugin_instance = PluginPlugin()
        self.plugin_manager.pm.register(plugin_plugin_instance, name="file:plugin")
        self.plugin_manager._plugin_names.append("file:plugin")
        self.plugin_manager._health["file:plugin"] = PluginHealth(name="file:plugin", loaded_at=datetime.now())
        self.plugin_manager.set_agent(self)

        for plugin_tool in self.plugin_manager.register_tools():
            self.register_tool(plugin_tool)

        # Startup health check: auto-heal degraded plugins and attempt
        # to reload disabled ones (non-fatal errors only).
        health = self.plugin_manager.check_and_repair()
        self._log_plugin_health(health)

    def _log_plugin_health(self, health: Dict[str, Any]) -> None:
        total = health.get("total", 0)
        healthy = len(health.get("already_healthy", []))
        healed = len(health.get("healed", []))
        reloaded = len(health.get("reloaded", []))
        still_disabled = health.get("still_disabled", [])

        summary = f"Plugins: {healthy}/{total} healthy"
        if healed:
            summary += f", {healed} healed"
        if reloaded:
            summary += f", {reloaded} reloaded"
        if still_disabled:
            names = [d["name"] for d in still_disabled]
            summary += f", {len(still_disabled)} disabled ({', '.join(names)})"

        logger = logging.getLogger("py_code_agent")
        logger.info("[Plugin] %s", summary)

        if healed:
            for item in health.get("healed", []):
                logger.info(
                    "[Plugin] Healed '%s' (was degraded with %d failures)",
                    item["name"],
                    item["previous_failures"],
                )
        if reloaded:
            for item in health.get("reloaded", []):
                logger.info(
                    "[Plugin] Reloaded '%s' (was: %s)",
                    item["name"],
                    item["previous_reason"],
                )
        if still_disabled:
            for item in still_disabled:
                logger.warning(
                    "[Plugin] Still disabled: '%s' (%s) — action: %s",
                    item["name"],
                    item["reason"],
                    item["action"],
                )
    
    async def run(self, input: str) -> AsyncIterator[Event]:
        """Run agent with input."""
        self.session.add_message(MessageRole.USER, input)

        yield Event(type=EventType.START, data={"input": input})

        if hasattr(self, "plugin_manager"):
            self.plugin_manager.call_on_agent_start(input)
        
        react_enabled = hasattr(self.config, "react") and self.config.react.enabled
        max_turns = getattr(self.config, "react", None) and self.config.react.max_turns or 10
        turn_count = 0

        while turn_count < max_turns:
            turn_count += 1
            messages = self._prepare_messages()
            tools = self._prepare_tools()

            if hasattr(self, "plugin_manager"):
                self.plugin_manager.call_on_llm_call(messages, tools)

            assistant_content = ""
            assistant_tool_calls: List[Dict[str, Any]] = []

            async for event in self.llm.stream(
                messages=messages,
                tools=tools,
                temperature=self.config.llm.temperature,
                max_tokens=self.config.llm.max_tokens,
            ):
                if event.type == EventType.CONTENT:
                    assistant_content += event.data.get("content", "")
                    yield event
                elif event.type == EventType.TOOL_CALL:
                    assistant_tool_calls.append(event.data)
                elif event.type == EventType.END:
                    pass

            # ReAct mode: parse Thought/Action from content
            if react_enabled and assistant_content:
                thought, action, parsed_tcs = self._parse_react_response(assistant_content)
                if parsed_tcs:
                    assistant_tool_calls = parsed_tcs
                    assistant_content = f"Thought: {thought}\nAction: {action}"

            if not assistant_tool_calls:
                self.session.add_message(MessageRole.ASSISTANT, assistant_content)
                break

            litellm_tcs = [
                {
                    "id": f"call_{uuid.uuid4().hex[:8]}",
                    "type": "function",
                    "function": {"name": tc.get("function", {}).get("name", tc.get("name", "")), "arguments": tc.get("function", {}).get("arguments", tc.get("arguments", "{}"))},
                }
                for tc in assistant_tool_calls
            ]
            self.session.add_message(
                MessageRole.ASSISTANT,
                assistant_content,
                tool_calls=litellm_tcs,
            )

            last_enhancement: Optional[Dict[str, Any]] = None
            turn_input = input
            for tc, litellm_tc in zip(assistant_tool_calls, litellm_tcs):
                tool_name = litellm_tc["function"]["name"]
                tool_args = litellm_tc["function"]["arguments"]

                if hasattr(self, "plugin_manager"):
                    self.plugin_manager.call_before_tool_execute(tool_name, tool_args)

                tool_result = await self._execute_tool(tc)

                if hasattr(self, "plugin_manager"):
                    self.plugin_manager.call_after_tool_execute(
                        tool_name, tool_args, tool_result
                    )

                obs_content = self._build_observation(tool_result, tool_name, tool_args)
                if react_enabled:
                    self.session.add_message(
                        MessageRole.TOOL,
                        obs_content,
                        tool_call_id=litellm_tc["id"],
                        name=tool_name,
                    )
                else:
                    self.session.add_message(
                        MessageRole.TOOL,
                        obs_content,
                        tool_call_id=litellm_tc["id"],
                        name=tool_name,
                    )
                yield Event(type=EventType.TOOL_RESULT, data=tool_result)

                # task_done now provides context for LLM to verify - don't auto-complete
                # The LLM should explicitly confirm after reviewing the verification context
                if tool_name == "task_done":
                    # Add explicit confirmation prompt
                    confirmation_msg = (
                        "\n## Task Completion Verification\n"
                        "You called task_done. Based on the filesystem context above:\n"
                        "- If files match expected output: Confirm completion (e.g., 'Task verified, completing')\n"
                        "- If files are missing or wrong: Continue working or fix issues\n"
                    )
                    self.session.add_message(MessageRole.USER, confirmation_msg)
                    continue

                if not tool_result.get("success") and hasattr(self, "plugin_manager") and self.plugin_manager is not None:
                    error_type = self._classify_error(tool_result.get("error", ""))
                    error_info = {
                        "error_type": error_type,
                        "error": tool_result.get("error", ""),
                        "diagnosis": "",
                        "suggestions": [],
                    }
                    enhancement = self.plugin_manager.call_enhance_tool_error(
                        tool_name, tool_args, error_info
                    )
                    if enhancement:
                        last_enhancement = enhancement

            # Track if task_done was called (but don't auto-complete)
            task_done_called = any(
                tc.get("function", {}).get("name", tc.get("name", "")) == "task_done"
                for tc in assistant_tool_calls
            )

            # Only prompt if task_done was never called
            if not task_done_called:
                msg = (
                    "IMPORTANT: You MUST call task_done to verify task completion.\n"
                    "ORIGINAL TASK: " + turn_input + "\n"
                    "Call task_done(original_task=..., expected_output=..., verification_context=...) to verify.\n"
                )
                if last_enhancement:
                    suggestions = last_enhancement.get("fix_suggestions", [])
                    if suggestions:
                        msg += "\nFIX REQUIRED:\n" + "\n".join(f"  {i+1}. {s}" for i, s in enumerate(suggestions))
                self.session.add_message(MessageRole.USER, msg)


        if hasattr(self, "plugin_manager"):
            self.plugin_manager.call_on_agent_end()

        yield Event(type=EventType.END, data={})
    
    def _prepare_messages(self) -> List[Message]:
        """Prepare messages for LLM."""
        messages = []
        
        if hasattr(self.config, "react") and self.config.react.enabled:
            base_prompt = (
                "You are a helpful AI coding assistant using the ReAct (Reasoning + Acting) pattern.\n\n"
                "Think step by step before taking actions. Follow this format:\n"
                "Thought: [Your reasoning about what to do next]\n"
                "Action: [The tool call or your final answer]\n"
                "Observation: [The result of the action]\n\n"
                'If you need to use a tool, format it as: tool_name({"arg": "value"})\n'
                "If you're done, put your final answer in Action without any tool call."
                "\n\n## Autonomous Coding Capability\n"
                "You have the ability to write and execute code to accomplish user requests:\n"
                "- Use `write_file` to create source code files\n"
                "- Use `execute_bash` to run code, tests, or build commands\n"
                "- Use `read_file` to verify code correctness\n"
                "- Don't wait for pre-built solutions — CREATE them yourself\n"
                "- When user asks for something complex, WRITE code to solve it\n\n"
                "## Self-Evaluation & Reflection\n"
                "After significant actions, evaluate your work:\n"
                "- Did the output meet user's requirements?\n"
                "- Are there edge cases not handled?\n"
                "- Could the solution be more efficient?\n"
                "- What did I learn from this task?\n\n"
                "## Tool Result Verification — NEVER TRUST OUTPUT\n"
                "You MUST inspect EVERY tool result. NEVER assume it worked:\n\n"
                "1. **EXPLICITLY check success/failure** — Look for error keywords, failure indicators\n"
                "2. **Verify actual output** — Read the output content, don't just scan for 'success'\n"
                "3. **Confirm file operations** — For file tools, use `ls` or `read_file` to verify files exist\n"
                "4. **Validate command results** — For bash, check exit code and actual output\n\n"
                "VERIFICATION RULES:\n"
                "- If tool claims success but you didn't see proof → VERIFY with another tool\n"
                "- If output looks suspicious → VERIFY with read_file or ls\n"
                "- If expected file not mentioned → USE read_file TO CHECK\n"
                "- NEVER trust 'Task completed' messages without evidence\n\n"
                "## Tool Failure Self-Recovery\n"
                "When a tool call fails (returns an error), do NOT immediately report failure.\n"
                "Diagnose the root cause and attempt recovery before giving up:\n\n"
                "1. **Missing dependency** — 'command not found', 'module not found', 'No such file or directory'\n"
                "   → Install the missing tool/runtime, then retry the original tool call\n"
                "   → e.g., `execute_bash('pip install <package>')` for Python\n"
                "   → e.g., `execute_bash('npm install <package>')` for Node.js\n"
                "   → e.g., `execute_bash('apt-get install -y <package>')` for system packages\n\n"
                "2. **Wrong tool used** — output is wrong format, skill workflow was skipped\n"
                "   → Re-read the relevant skill with `get_skill(name)` and follow its workflow\n"
                "   → Do NOT substitute with a different tool that produces similar-looking but wrong output\n\n"
                "3. **Partial failure** — some steps worked but final output is wrong\n"
                "   → Fix only the failing step, preserve work from successful steps\n"
                "   → Do NOT restart from scratch if earlier steps succeeded\n\n"
                "4. **Permission/environment issue** — sandbox restrictions, path errors\n"
                "   → Use `execute_bash('ls /allowed/path')` to find valid paths\n"
                "   → Adjust tool arguments to use available paths\n\n"
                "5. **Alternative approach** — command not found, tool unavailable\n"
                "   → Find alternative: `which tar gzip 7z` to check available tools\n"
                "   → Use tar.gz instead of zip, or other available alternatives\n"
                "   → NEVER fail just because one approach doesn't work\n\n"
                "6. **Missing environment** — command not found, package missing\n"
                "   → Auto-install: `execute_bash('pip install X')` for Python packages\n"
                "   → Auto-install: `execute_bash('npm install X')` for Node.js packages\n"
                "   → Auto-install: `execute_bash('apt-get install -y X')` for system packages\n"
                "   → Build from source if pre-built unavailable\n"
                "   → NEVER skip the task just because environment is missing\n\n"
                "IMPORTANT: You have multiple turns. Use them to recover from failures.\n"
                "After fixing, CONTINUE with the task — do not report failure prematurely.\n"
                "\n## Goal-Oriented Execution (PRIMARY)\n"
                "Your PRIMARY objective is to FULFILL THE USER'S REQUEST.\n"
                "- Task ends when user's goal is ACHIEVED, NOT when you encounter an error\n"
                "- If one method fails, try ALTERNATIVES until success\n"
                "- Do NOT give up or report failure prematurely\n"
                "- Always verify final result meets user's requirements\n"
                "- When command not found: check available tools, use alternatives (tar.gz instead of zip)\n\n"
                "\n## Task Completion\n"
                "When you believe the original task is complete, you MUST call `task_done` to verify.\n"
                "Provide verification_context explaining what you created and how it matches expected output.\n"
                "This is the ONLY way to end the session. Do not just stop responding."
            )
        else:
            base_prompt = (
                "You are a helpful AI coding assistant. You have access to tools for file operations, bash commands, and more. Use these tools when needed to help the user."
                "\n\n## Autonomous Coding Capability\n"
                "You have the ability to write and execute code to accomplish user requests:\n"
                "- Use `write_file` to create source code files\n"
                "- Use `execute_bash` to run code, tests, or build commands\n"
                "- Use `read_file` to verify code correctness\n"
                "- Don't wait for pre-built solutions — CREATE them yourself\n"
                "- When user asks for something complex, WRITE code to solve it\n\n"
                "## Self-Evaluation & Reflection\n"
                "After significant actions, evaluate your work:\n"
                "- Did the output meet user's requirements?\n"
                "- Are there edge cases not handled?\n"
                "- Could the solution be more efficient?\n"
                "- What did I learn from this task?\n\n"
                "## Tool Result Verification — NEVER TRUST OUTPUT\n"
                "You MUST inspect EVERY tool result. NEVER assume it worked:\n"
                "1. EXPLICITLY check success/failure — look for error keywords\n"
                "2. Verify actual output — read content, don't just scan for 'success'\n"
                "3. Confirm file operations — use `ls` or `read_file` to verify\n"
                "4. NEVER trust 'Task completed' without evidence\n\n"
                "VERIFICATION RULES:\n"
                "- If tool claims success but you didn't see proof → VERIFY with another tool\n"
                "- If output looks suspicious → VERIFY with read_file or ls\n"
                "- If expected file not mentioned → USE read_file TO CHECK\n"
                "\n## Tool Failure Self-Recovery\n"
                "When a tool call fails, diagnose the root cause and attempt recovery:\n"
                "1. Missing dependency → install it, then retry\n"
                "2. Wrong tool used → re-read relevant skill, follow its workflow\n"
                "3. Partial failure → fix only the failing step, preserve successful work\n"
                "4. Permission issue → find valid paths, adjust tool arguments\n"
                "5. Alternative approach → command not found, use alternatives\n"
                "   → Check available tools with `which tar gzip 7z`\n"
                "   → Use tar.gz instead of zip when zip unavailable\n"
                "6. Missing environment → auto-install dependencies\n"
                "   → pip install X for Python, npm install X for Node.js\n"
                "   → apt-get install -y X for system packages\n"
                "   → NEVER skip task just because environment missing\n\n"
                "IMPORTANT: You have multiple turns. Use them to recover — do not report failure prematurely."
                "\n\n## Goal-Oriented Execution (PRIMARY)\n"
                "Your PRIMARY objective is to FULFILL THE USER'S REQUEST.\n"
                "- Task ends when user's goal is ACHIEVED, NOT when you encounter an error\n"
                "- If one method fails, try ALTERNATIVES until success\n"
                "- Do NOT give up or report failure prematurely\n"
                "- Always verify final result meets user's requirements\n"
                "- Auto-install missing packages when environment incomplete\n\n"
                "\n## Task Completion\n"
                "When you believe the task is done, you MUST call `task_done` with verification_context to verify.\n"
                "This is the ONLY way to end the session. Do not just stop responding."
            )
        
        plugin_prompt = ""
        if hasattr(self, "plugin_manager") and self.plugin_manager is not None:
            plugin_prompt = self.plugin_manager.call_get_system_prompt()
        
        if plugin_prompt:
            system_content = base_prompt + "\n\n" + plugin_prompt
        else:
            system_content = base_prompt
        
        messages.append(Message(
            role=MessageRole.SYSTEM,
            content=system_content
        ))
        
        # Add session messages (using new tree-based context)
        session_messages = self.session.get_current_context() if hasattr(self.session, 'get_current_context') else self.session.messages
        for msg in session_messages:
            msg_kwargs = {}
            if msg["role"] == MessageRole.ASSISTANT and msg.get("tool_calls"):
                msg_kwargs["tool_calls"] = msg["tool_calls"]
            if msg["role"] == MessageRole.TOOL:
                msg_kwargs["tool_call_id"] = msg.get("tool_call_id", "")
                msg_kwargs["name"] = msg.get("name", "")
            messages.append(Message(
                role=msg["role"],
                content=msg["content"],
                **msg_kwargs,
            ))
        
        return messages
    
    def _parse_react_response(self, content: str) -> Tuple[str, str, List[Dict[str, Any]]]:
        """Parse ReAct-style response into Thought, Action, and tool_calls.
        
        Returns:
            (thought, action, tool_calls): thought is the reasoning,
            action is either a tool call or final answer,
            tool_calls is a list of tool call dicts if action is a tool call
        """
        thought = ""
        action = ""
        tool_calls: List[Dict[str, Any]] = []
        
        thought_match = content.split("Thought:")
        if len(thought_match) > 1:
            thought_part = thought_match[1].split("Action:")[0] if "Action:" in thought_match[1] else thought_match[1]
            thought = thought_part.strip()
        
        action_match = content.split("Action:")
        if len(action_match) > 1:
            action_part = action_match[1].split("Observation:")[0] if "Observation:" in action_match[1] else action_match[1]
            action = action_part.strip()
            
            if action.startswith("[") or ("(" in action and ")" in action):
                try:
                    if action.startswith("["):
                        parsed = json.loads(action)
                        def transform_tool_call(tc):
                            if "function" in tc:
                                return tc
                            return {
                                "id": tc.get("id", f"call_{hash(str(tc)) % 1000000}"),
                                "type": "function",
                                "function": {
                                    "name": tc.get("name", ""),
                                    "arguments": tc.get("arguments", "{}")
                                }
                            }
                        if isinstance(parsed, list):
                            tool_calls = [transform_tool_call(tc) for tc in parsed]
                        else:
                            tool_calls = [transform_tool_call(parsed)]
                    else:
                        func_name = action.split("(")[0].strip()
                        args_str = action.split("(")[1].rsplit(")", 1)[0]
                        try:
                            args = json.loads("{" + args_str + "}") if args_str else {}
                        except:
                            args = {"_raw": args_str}
                        tool_calls = [{
                            "id": f"call_{hash(action) % 1000000}",
                            "type": "function",
                            "function": {
                                "name": func_name,
                                "arguments": json.dumps(args)
                            }
                        }]
                except Exception:
                    tool_calls = []
        
        return thought, action, tool_calls

    def _prepare_tools(self) -> List[Dict[str, Any]]:
        """Prepare tools for LLM."""
        tools = []
        
        for tool in self.tools.values():
            definition = tool.definition
            tool_spec = {
                "type": "function",
                "function": {
                    "name": definition.name,
                    "description": definition.description,
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            }
            
            for param in definition.parameters:
                tool_spec["function"]["parameters"]["properties"][param.name] = {
                    "type": param.type.value,
                    "description": param.description,
                }
                if param.enum:
                    tool_spec["function"]["parameters"]["properties"][param.name]["enum"] = param.enum
                if param.required:
                    tool_spec["function"]["parameters"]["required"].append(param.name)
            
            tools.append(tool_spec)
        
        return tools
    
    def _validate_tool_arguments(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> Optional[str]:
        """Validate tool arguments against schema. Returns error message or None if valid."""
        tool = self.tools.get(tool_name)
        if not tool:
            return None

        definition = getattr(tool, "definition", None)
        if not definition or not definition.parameters:
            return None

        for param in definition.parameters:
            value = arguments.get(param.name)
            if value is None:
                if param.required and param.default is None:
                    return (
                        f"Missing required parameter '{param.name}' for tool '{tool_name}'. "
                        f"Valid parameters: {', '.join(p.name for p in definition.parameters)}"
                    )
                continue

            expected = param.type.value if hasattr(param.type, "value") else str(param.type)
            actual_type = type(value).__name__
            valid = False
            if expected == "string" and isinstance(value, str):
                valid = True
            elif expected == "integer" and isinstance(value, int) and not isinstance(value, bool):
                valid = True
            elif expected == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
                valid = True
            elif expected == "boolean" and isinstance(value, bool):
                valid = True
            elif expected == "array" and isinstance(value, list):
                valid = True
            elif expected == "object" and isinstance(value, dict):
                valid = True

            if not valid:
                example = json.dumps({param.name: self._example_value(expected)}, indent=2)
                return (
                    f"Wrong type for parameter '{param.name}' in tool '{tool_name}': "
                    f"expected {expected} but got {actual_type}. "
                    f"Make sure JSON keys and string values are properly quoted. "
                    f"Example: {example}"
                )

        return None

    def _example_value(self, type_name: str) -> Any:
        """Return an example value for a parameter type."""
        examples = {
            "string": "hello world",
            "integer": 42,
            "number": 3.14,
            "boolean": True,
            "array": ["item1", "item2"],
            "object": {"key": "value"},
        }
        return examples.get(type_name, "value")

    async def _execute_tool(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool. Layer 5: auto-repair tool execute errors via AST patch."""
        tool_name = data.get("name")
        arguments_raw = data.get("arguments", "{}")
        tool_call_id = data.get("id")

        if tool_name not in self.tools:
            return {
                "success": False,
                "error": f"Tool not found: {tool_name}",
                "tool_call_id": tool_call_id,
            }

        tool = self.tools[tool_name]

        try:
            if isinstance(arguments_raw, str):
                arguments = json.loads(arguments_raw)
            elif isinstance(arguments_raw, dict):
                arguments = arguments_raw
            else:
                arguments = {}
        except json.JSONDecodeError as e:
            # Try to fix truncated JSON where LLM cuts off long strings
            fixed = self._fix_truncated_json(arguments_raw) if isinstance(arguments_raw, str) else None
            if fixed is not None:
                arguments = fixed
            else:
                return {
                    "success": False,
                    "error": (
                        f"Invalid JSON in tool arguments: {e}. "
                        f"Make sure all keys and string values are quoted. "
                        f"Example: {json.dumps({'param': 'value'}, indent=2)}"
                    ),
                    "tool_call_id": tool_call_id,
                }

        validation_error = self._validate_tool_arguments(tool_name, arguments)
        if validation_error:
            return {
                "success": False,
                "error": validation_error,
                "tool_call_id": tool_call_id,
            }

        try:
            result = await tool.execute(**arguments)
            return {
                "success": result.success,
                "data": result.data,
                "error": result.error,
                "summary": result.summary,
                "tool_call_id": tool_call_id,
            }
        except Exception as e:
            from py_code_agent.plugins.auto_repair import AiAutoRepair
            ar = AiAutoRepair(f"tool:{tool_name}", tool)
            patched = ar.fix_tool_execute(tool, e)
            if patched:
                logging.getLogger("py_code_agent").info(
                    "[AiAutoRepair] Layer5: retrying tool '%s' after AST patch", tool_name
                )
                try:
                    result = await tool.execute(**arguments)
                    return {
                        "success": result.success,
                        "data": result.data,
                        "error": result.error,
                        "summary": result.summary,
                        "tool_call_id": tool_call_id,
                    }
                except Exception as retry_err:
                    return {
                        "success": False,
                        "error": f"[auto-repair failed] {retry_err}",
                        "tool_call_id": tool_call_id,
                    }
            return {
                "success": False,
                "error": str(e),
                "tool_call_id": tool_call_id,
            }
    
    def reset(self) -> None:
        """Reset agent."""
        self.session = Session()

    def _build_observation(
        self, tool_result: Dict[str, Any], tool_name: str, tool_args: Any
    ) -> str:
        """Build observation string for tool result. On error, call enhance_tool_error hooks.

        If tool succeeded: returns plain JSON observation.
        If tool failed: classifies error, calls plugin hooks for enhancement,
        returns structured diagnosis + fix suggestions to help the LLM recover.
        """
        if tool_result.get("success", True):
            return json.dumps(tool_result)

        error_msg = tool_result.get("error", "Unknown error")
        error_type = self._classify_error(error_msg)

        error_info = {
            "error_type": error_type,
            "error": error_msg,
            "diagnosis": "",
            "suggestions": [],
        }

        if hasattr(self, "plugin_manager") and self.plugin_manager is not None:
            enhanced = self.plugin_manager.call_enhance_tool_error(
                tool_name, tool_args, error_info
            )
            if enhanced:
                error_type = enhanced.get("error_type", error_type)
                diagnosis = enhanced.get("diagnosis", "")
                fix_suggestions = enhanced.get("fix_suggestions", [])
                confidence = enhanced.get("confidence", 1.0)

                suggestions_text = ""
                if fix_suggestions:
                    suggestions_text = "\n".join(
                        f"  {i + 1}. {s}" for i, s in enumerate(fix_suggestions)
                    )

                return json.dumps(
                    {
                        "success": False,
                        "error_type": error_type,
                        "error": error_msg,
                        "diagnosis": diagnosis,
                        "fix_suggestions": fix_suggestions,
                        "confidence": confidence,
                        "enhanced_observation": (
                            f"[{error_type.upper()}] {diagnosis}\n"
                            f"Suggested fixes:\n{suggestions_text}\n"
                            f"Tool call: {tool_name}({json.dumps(tool_args, ensure_ascii=False) if tool_args else '{}'})\n"
                            f"Raw error: {error_msg}"
                        ),
                    },
                    ensure_ascii=False,
                )

        return json.dumps(tool_result)

    def _classify_error(self, error_msg: str) -> str:
        msg_lower = error_msg.lower()
        if any(
            x in msg_lower
            for x in [
                "command not found",
                "no such file",
                "not installed",
                "executable",
            ]
        ):
            return "missing_dependency"
        if any(
            x in msg_lower
            for x in [
                "module not found",
                "import error",
                "importerror",
                "no module named",
            ]
        ):
            return "missing_dependency"
        if any(
            x in msg_lower for x in ["permission denied", "access denied", "eacces"]
        ):
            return "permission_denied"
        if any(x in msg_lower for x in ["invalid argument", "unexpected keyword", "type error"]):
            return "invalid_arguments"
        if any(
            x in msg_lower
            for x in [
                "timeout",
                "timed out",
                "connection refused",
                "network error",
            ]
        ):
            return "network_timeout"
        if any(x in msg_lower for x in ["invalid json", "unterminated string", "invalid control character"]):
            return "invalid_json_args"
        if any(
            x in msg_lower
            for x in [
                "skill",
                "workflow",
                "plugin",
            ]
        ):
            return "skill_workflow_error"
        return "execution_error"

    def _fix_json_with_embedded_newlines(self, raw: str) -> Optional[Dict[str, Any]]:
        in_string = False
        escaped = False
        open_braces = 0
        open_brackets = 0
        chars = list(raw)
        i = 0
        while i < len(chars):
            c = chars[i]
            if escaped:
                escaped = False
                i += 1
                continue
            if c == "\\":
                escaped = True
                i += 1
                continue
            if c == '"' and not escaped:
                in_string = not in_string
            elif not in_string:
                if c == "{":
                    open_braces += 1
                elif c == "}":
                    open_braces -= 1
                elif c == "[":
                    open_brackets += 1
                elif c == "]":
                    open_brackets -= 1
                elif c == "\n":
                    chars[i] = "\\n"
            i += 1

        fixed = "".join(chars)

        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass
        return None

    def _fix_truncated_json(self, raw: str) -> Optional[Dict[str, Any]]:
        open_braces = 0
        open_brackets = 0
        in_string = False
        escaped = False
        
        for c in raw:
            if escaped:
                escaped = False
                continue
            if c == "\\":
                escaped = True
                continue
            if c == '"' and not escaped:
                in_string = not in_string
            elif not in_string:
                if c == "{":
                    open_braces += 1
                elif c == "}":
                    open_braces -= 1
                elif c == "[":
                    open_brackets += 1
                elif c == "]":
                    open_brackets -= 1

        fixed = raw
        if open_braces > 0:
            fixed += "}" * open_braces
        if open_brackets > 0:
            fixed += "]" * open_brackets
        if in_string:
            fixed += '"'

        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

        if in_string or open_braces > 0 or open_brackets > 0:
            truncated = self._truncate_to_complete_kv(raw)
            if truncated:
                try:
                    return json.loads(truncated)
                except json.JSONDecodeError:
                    pass

        if in_string and ("<<" in raw or "EOF" in raw):
            heredoc_fixed = self._fix_heredoc_truncation(raw)
            if heredoc_fixed:
                try:
                    return json.loads(heredoc_fixed)
                except json.JSONDecodeError:
                    pass

        return None

    def _fix_heredoc_truncation(self, raw: str) -> Optional[str]:
        try:
            data = json.loads(raw + '"')
            cmd = data.get("command", "")
            if "<<" in cmd:
                last_eof = cmd.rfind("EOF")
                if last_eof > 0:
                    truncated_cmd = cmd[:last_eof + 3] + "'"
                    data["command"] = truncated_cmd
                    return json.dumps(data)
        except:
            pass
        return None

    def _truncate_to_complete_kv(self, s: str) -> Optional[str]:
        last_brace = s.rfind("}")
        if last_brace == -1:
            return None
        
        for pos in range(last_brace, -1, -1):
            truncated = s[: pos + 1].strip()
            if not truncated.endswith("}"):
                continue
            try:
                result = json.loads(truncated)
                if isinstance(result, dict):
                    return truncated
            except json.JSONDecodeError:
                continue
        
        return None
    
    def save_state(self) -> Dict[str, Any]:
        """Save agent state."""
        return {
            "agent_id": self.agent_id,
            "session": self.session.to_dict(),
        }
    
    def load_state(self, state: Dict[str, Any]) -> None:
        """Load agent state."""
        self.agent_id = state.get("agent_id", self.agent_id)
        if "session" in state:
            self.session = Session.from_dict(state["session"])

    def shutdown(self) -> None:
        """Shut down the agent and its plugin manager."""
        if hasattr(self, "plugin_manager"):
            self.plugin_manager.shutdown()
