"""Plugin AI-powered self-repair system.

Architecture:
  - Layers 1-4: fast hardcoded runtime patches (wrap/inject/setattr)
  - Layer 5: LLM-powered deep repair — analyzes error + generates AST patch
    when simple fixes are insufficient.

The LLM is called ONLY for Layer 5 (tool execute errors) and ONLY when
the simple try/except AST patch doesn't resolve the issue.
"""

from __future__ import annotations

import ast
import asyncio
import copy
import importlib
import io
import logging
import os
import re
import subprocess
import sys
import textwrap
import traceback
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set, Type

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from py_code_agent.llm.litellm_provider import LiteLLMProvider

_HOOK_METHODS: Set[str] = {
    # ToolHooks
    "register_tools",
    "before_tool_execute",
    "after_tool_execute",
    "enhance_tool_error",
    "enhance_tool_error_priority",
    # AgentHooks
    "on_agent_start",
    "on_agent_end",
    "on_llm_call",
    "on_llm_response",
    "get_system_prompt",
    "on_plugin_heartbeat",
    "get_capabilities",
    # StreamingHooks
    "on_message_start",
    "on_message_update",
    "on_message_end",
    "on_tool_execution_start",
    "on_tool_execution_update",
    "on_tool_execution_end",
    # SessionHooks
    "on_session_before_compact",
    "on_session_compacted",
    "on_session_fork",
    "on_session_switch",
    "on_session_tree",
    # ModelHooks
    "on_model_select",
    "on_context_access",
    # TurnHooks
    "on_turn_start",
    "on_turn_end",
    # ExtensionHooks (registration hooks - less critical but include for completeness)
    "register_commands",
    "register_shortcuts",
    "register_cli_flags",
}

_MAX_LLM_REPAIRS = 2
_LLM_TIMEOUT = 30

_SYSTEM_PROMPT = """You are an expert Python debugger specializing in plugin systems.

Given a plugin tool that crashes with an error, your task is to:
1. Analyze the error, stack trace, and source code
2. Generate a fixed version of the `execute()` method
3. Return ONLY the corrected Python code — no explanation, no markdown

Rules:
- The method must be `async def execute(self, **kwargs) -> ToolResult`
- Always catch exceptions and return `ToolResult.fail(str(e))`
- Preserve the original logic — fix only the broken part
- Do NOT change the class structure or other methods
- Do NOT add new imports that aren't already in the file
- Keep the method signature exactly as: `async def execute(self, **kwargs)`

Return just the Python code for the method body wrapped in the class."""


class AiAutoRepair:
    """AI-powered self-repair engine for plugin code errors.

    Layers 1-4: fast runtime patches (synchronous, no LLM).
    Layer 5:   LLM analyzes complex errors and generates AST patches.
    """

    def __init__(
        self,
        plugin_name: str,
        plugin_instance: Any,
        llm_provider: Optional["LiteLLMProvider"] = None,
        max_llm_repairs: int = _MAX_LLM_REPAIRS,
    ) -> None:
        self.plugin_name = plugin_name
        self.plugin = plugin_instance
        self._wrapped_methods: Set[str] = set()
        self._last_error: Optional[BaseException] = None
        self._llm_repairs: int = 0
        self._max_llm_repairs = max_llm_repairs
        self._llm_provider = llm_provider
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ai-repair-")

    @property
    def llm_available(self) -> bool:
        return self._llm_provider is not None

    # ------------------------------------------------------------------
    # Layer 1 — Hook runtime errors: wrap with try/except
    # ------------------------------------------------------------------

    def wrap_method(self, method_name: str, call_orig: Callable[..., Any]) -> bool:
        """Wrap a plugin hook method so it never propagates exceptions."""
        if method_name in self._wrapped_methods:
            return True
        method = getattr(self.plugin, method_name, None)
        if method is None:
            return False
        original = method

        def safe_call(*args: Any, **kwargs: Any) -> Any:
            try:
                return original(*args, **kwargs)
            except BaseException as e:
                logger.warning(
                    "[AiAutoRepair] Wrapped '%s' in '%s' caught: %s",
                    method_name,
                    self.plugin_name,
                    e,
                )
                return None

        try:
            setattr(self.plugin, method_name, safe_call)
            self._wrapped_methods.add(method_name)
            logger.info("[AiAutoRepair] Layer1: wrapped '%s' in '%s'", method_name, self.plugin_name)
            return True
        except (TypeError, AttributeError):
            return False

    # ------------------------------------------------------------------
    # Layer 2 — Missing hook methods: inject stubs
    # ------------------------------------------------------------------

    def inject_stub(self, method_name: str) -> bool:
        """Add a no-op stub for a missing hook method."""
        if hasattr(self.plugin, method_name):
            return True
        try:
            setattr(self.plugin, method_name, lambda *a, **k: None)
            logger.info("[AiAutoRepair] Layer2: injected stub '%s' into '%s'", method_name, self.plugin_name)
            return True
        except (TypeError, AttributeError):
            return False

    def inject_all_stubs(self) -> int:
        """Inject stubs for all missing hook methods."""
        return sum(1 for name in _HOOK_METHODS if not hasattr(self.plugin, name) and self.inject_stub(name))

    # ------------------------------------------------------------------
    # Layer 3 — Import errors: pip install
    # ------------------------------------------------------------------

    def fix_import_error(self, error: ImportError) -> bool:
        """Attempt pip install for missing module."""
        msg = str(error)
        patterns = [
            r"No module named ['\"]([^'\"]+)['\"]",
            r"cannot import name ['\"]([^'\"]+)['\"] from ['\"]([^'\"]+)['\"]",
        ]
        module_name = next(
            (re.search(p, msg).group(1) for p in patterns if re.search(p, msg)),
            None,
        )
        if not module_name or module_name.startswith("py_code_agent"):
            return False
        try:
            logger.info("[AiAutoRepair] Layer3: pip install '%s'", module_name)
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", module_name, "--quiet"],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0:
                logger.info("[AiAutoRepair] Layer3: installed '%s'", module_name)
                return True
            logger.warning("[AiAutoRepair] Layer3: pip install failed: %s", result.stderr)
            return False
        except Exception as e:
            logger.warning("[AiAutoRepair] Layer3: pip install '%s' raised %s", module_name, e)
            return False

    # ------------------------------------------------------------------
    # Layer 4 — Attribute errors: inject missing attribute
    # ------------------------------------------------------------------

    def fix_attribute_error(self, error: AttributeError) -> bool:
        """Inject missing attribute with sensible default."""
        attr_name = error.name
        if attr_name is None:
            msg = str(error)
            m = re.search(r"has no attribute ['\"]?(\w+)['\"]?", msg)
            if m:
                attr_name = m.group(1)
        if attr_name is None or attr_name.startswith("_") or attr_name.isupper():
            return False
        if hasattr(self.plugin, attr_name):
            return False
        default: Any = None
        ln = attr_name.lower()
        if "logger" in ln:
            default = logging.getLogger(f"{self.plugin_name}.{attr_name}")
        elif "log" in ln:
            default = []
        elif "cache" in ln:
            default = {}
        elif "count" in ln or "n_" in ln:
            default = 0
        try:
            setattr(self.plugin, attr_name, default)
            logger.info("[AiAutoRepair] Layer4: injected '%s' = %r onto '%s'", attr_name, default, self.plugin_name)
            return True
        except (TypeError, AttributeError):
            return False

    # ------------------------------------------------------------------
    # Layer 5 — Tool execute errors: LLM-powered AST patch
    # ------------------------------------------------------------------

    def fix_tool_execute(
        self, tool_instance: Any, error: Exception, tool_source: Optional[str] = None
    ) -> bool:
        """Attempt to fix tool execute() via LLM-generated AST patch.

        Strategy:
        1. If LLM is available and simple AST wrap failed, call LLM.
        2. Otherwise fall back to simple try/except AST patch.
        """
        tool_class = type(tool_instance)
        module = sys.modules.get(tool_class.__module__)
        source_path, source_text = self._get_source(module)
        if source_text is None:
            return False

        exc_type = type(error).__name__
        exc_msg = str(error)
        stack = traceback.format_exception(type(error), error, error.__traceback__)

        if self._llm_repairs < self._max_llm_repairs and self.llm_available:
            self._llm_repairs += 1
            fixed = self._llm_fix(source_text, tool_class.__name__, exc_type, exc_msg, stack)
            if fixed:
                return self._apply_and_reload(source_path, fixed, tool_instance, tool_class)
            logger.warning("[AiAutoRepair] Layer5: LLM fix failed, falling back to simple patch")
        return self._simple_fix(source_text, tool_class.__name__, tool_instance, tool_class)

    def _get_source(self, module: Any) -> tuple[Optional[Path], Optional[str]]:
        """Get source file path and content for a module."""
        if module is None:
            return None, None
        path = Path(getattr(module, "__file__", "") or "")
        if not path.exists():
            return None, None
        try:
            return path, path.read_text(encoding="utf-8")
        except (OSError, IOError):
            return None, None

    def _llm_fix(
        self, source: str, class_name: str, exc_type: str, exc_msg: str, stack: List[str]
    ) -> Optional[str]:
        """Call LLM to generate a fix for the broken execute() method."""
        user_prompt = f"""## Error
- Exception: {exc_type}: {exc_msg}
- Stack trace:
{''.join(stack)}

## Source code of {class_name}
```python
{source}
```

## Task
Fix the `execute()` method so it no longer raises {exc_type}. Return ONLY the Python code — the complete fixed class including the execute method wrapped in try/except."""
        try:
            if asyncio.get_event_loop().is_running():
                future = self._executor.submit(
                    self._llm_call_sync, user_prompt
                )
                code = future.result(timeout=_LLM_TIMEOUT)
            else:
                code = asyncio.run(self._llm_call_async(user_prompt))
        except Exception as e:
            logger.warning("[AiAutoRepair] Layer5 LLM call failed: %s", e)
            return None

        if not code:
            return None

        code = self._extract_code(code)
        if not self._verify_code(code):
            logger.warning("[AiAutoRepair] Layer5: LLM output failed AST verification")
            return None

        return code

    def _llm_call_sync(self, user_prompt: str) -> str:
        """Run async LLM call in a thread (for sync contexts)."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self._llm_call_async(user_prompt))
        finally:
            loop.close()

    async def _llm_call_async(self, user_prompt: str) -> str:
        """Async LLM call via LiteLLM."""
        from py_code_agent.llm.litellm_provider import Message

        messages = [
            Message(role="system", content=_SYSTEM_PROMPT),
            Message(role="user", content=user_prompt),
        ]
        result = await self._llm_provider.complete(messages, max_tokens=2000, temperature=0.3)
        return result.get("content", "").strip()

    def _extract_code(self, raw: str) -> str:
        """Extract Python code from LLM response (strip markdown fences)."""
        code = raw.strip()
        for fence in ("```python", "```py", "```"):
            if code.startswith(fence):
                code = code[len(fence):]
            if code.endswith(fence):
                code = code[: -len(fence)]
        return code.strip()

    def _verify_code(self, code: str) -> bool:
        """Verify LLM output is valid Python."""
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "execute":
                    return True
            return False
        except SyntaxError:
            return False

    def _simple_fix(
        self,
        source: str,
        class_name: str,
        tool_instance: Any,
        tool_class: Type,
    ) -> bool:
        """Fall back to wrapping execute() in try/except via AST."""
        patched = self._patch_try_except(source, class_name)
        if patched is None:
            return False
        source_path, _ = self._get_source(sys.modules.get(tool_class.__module__))
        if source_path is None:
            return False
        return self._apply_and_reload(source_path, patched, tool_instance, tool_class)

    def _patch_try_except(self, source: str, class_name: str) -> Optional[str]:
        """Wrap execute() method body in try/except via AST."""
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return None

        patched = False

        class Patcher(ast.NodeTransformer):
            def visit_FunctionDef(self, node):
                return self._wrap(node)

            def visit_AsyncFunctionDef(self, node):
                return self._wrap(node)

            def _wrap(self, node):
                nonlocal patched
                if node.name == "execute" and node.args.args and node.args.args[0].arg == "self":
                    node.body = [
                        ast.Try(
                            body=node.body,
                            handlers=[
                                ast.ExceptHandler(
                                    type=ast.Name(id="Exception", ctx=ast.Load()),
                                    name="_e",
                                    body=[
                                        ast.Return(
                                            value=ast.Call(
                                                func=ast.Attribute(
                                                    value=ast.Name(id="ToolResult", ctx=ast.Load()),
                                                    attr="fail",
                                                    ctx=ast.Load(),
                                                ),
                                                args=[
                                                    ast.Call(
                                                        func=ast.Name(id="str", ctx=ast.Load()),
                                                        args=[ast.Name(id="_e", ctx=ast.Load())],
                                                        keywords=[],
                                                    )
                                                ],
                                                keywords=[],
                                            )
                                        )
                                    ],
                                    orelse=[], finalbody=[],
                                )
                            ],
                            orelse=[], finalbody=[],
                        )
                    ]
                    patched = True
                return node

        try:
            new_tree = Patcher().visit(tree)
            ast.fix_missing_locations(new_tree)
        except Exception:
            return None

        if not patched:
            return None

        try:
            return ast.unparse(new_tree)
        except Exception:
            return None

    def _apply_and_reload(
        self,
        source_path: Path,
        code: str,
        tool_instance: Any,
        tool_class: Type,
    ) -> bool:
        """Write fixed code to file, reload module, update instance."""
        try:
            bak = source_path.with_suffix(source_path.suffix + ".bak")
            bak.write_bytes(source_path.read_bytes())
        except (OSError, IOError):
            bak = None

        try:
            source_path.write_text(code, encoding="utf-8")
        except (OSError, IOError, PermissionError) as e:
            logger.warning("[AiAutoRepair] Layer5: could not write %s: %s", source_path, e)
            return False

        try:
            new_module = importlib.reload(sys.modules[tool_class.__module__])
            new_class = getattr(new_module, tool_class.__name__, None)
            if new_class is None:
                raise RuntimeError(f"class {tool_class.__name__} not found after reload")
            self._sync_instance(tool_instance, new_class)
            logger.info("[AiAutoRepair] Layer5: applied fix to %s from %s", tool_class.__name__, source_path)
            return True
        except Exception as e:
            logger.warning("[AiAutoRepair] Layer5: reload failed: %s — reverting", e)
            if bak and bak.exists():
                source_path.write_bytes(bak.read_bytes())
                bak.unlink(missing_ok=True)
            return False

    def _sync_instance(self, old: Any, new_class: Type) -> None:
        try:
            for k, v in vars(new_class).items():
                if not k.startswith("_"):
                    setattr(old, k, copy.copy(v) if hasattr(copy, "copy") else v)
            for k, v in vars(new_class.__new__(new_class)).items():
                setattr(old, k, copy.copy(v) if hasattr(copy, "copy") else v)
        except Exception as e:
            logger.debug("[AiAutoRepair] Layer5: instance sync: %s", e)
