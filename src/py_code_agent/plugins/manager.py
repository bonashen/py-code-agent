"""Plugin manager with self-healing for Py Code Agent."""

from __future__ import annotations

import importlib
import importlib.util
import logging
import re
import sys
import traceback
import typing
from concurrent.futures import ThreadPoolExecutor, TimeoutError as TimeoutExpired
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Type

import pluggy

from py_code_agent.config.models import PluginConfig
from py_code_agent.plugins import hooks
from py_code_agent.plugins.auto_repair import AiAutoRepair
from py_code_agent.tools.base import BaseTool, ToolDefinition, ToolParameter, ToolParameterType, ToolResult

if typing.TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Exceptions that a plugin MUST NOT propagate — they are always fatal to core.
_FATAL_PLUGIN_EXCEPTIONS: Tuple[Type[BaseException], ...] = (
    SystemExit,
    KeyboardInterrupt,
    MemoryError,
    RecursionError,
    AssertionError,
)

# Exceptions that indicate a plugin programming error (disable immediately).
_UNRECOVERABLE_PLUGIN_EXCEPTIONS: Tuple[Type[Exception], ...] = (
    TypeError,
    AttributeError,
    NameError,
)


@dataclass
class PluginHealth:
    """Health status for a single plugin."""

    name: str
    loaded_at: Optional[datetime] = None
    success_count: int = 0
    failure_count: int = 0
    last_error: Optional[str] = None
    last_success: Optional[datetime] = None
    disabled: bool = False
    disabled_reason: Optional[str] = None  # NEW: why the plugin was disabled

    @property
    def is_healthy(self) -> bool:
        return not self.disabled and self.failure_count < 3

    @property
    def status(self) -> str:
        if self.disabled:
            reason = f" ({self.disabled_reason})" if self.disabled_reason else ""
            return f"DISABLED{reason}"
        if self.failure_count > 0:
            return f"DEGRADED (failures={self.failure_count})"
        return "HEALTHY"


class PluginManager:
    """Manages plugin discovery, loading, and hook invocation with self-healing.

    Hardening principles:
    1. All plugin code runs in isolated try/except — never crashes the core.
    2. Hook calls are protected by per-plugin timeouts.
    3. Fatal Python exceptions (SystemExit, MemoryError, etc.) disable the
       plugin *immediately* without propagating.
    4. Plugin imports are sandboxed from core — modules prefixed with
       "py_code_agent" are never overwritten.
    5. Plugins that exhaust resources are killed via timeout and disabled.
    """

    #: Timeout for each hook invocation (seconds). 0 = disabled.
    DEFAULT_HOOK_TIMEOUT: float = 5.0

    #: Failure threshold — plugin is considered unhealthy above this.
    DEFAULT_FAILURE_THRESHOLD: int = 3

    #: Failure threshold — plugin is auto-disabled above this.
    DEFAULT_DISABLE_THRESHOLD: int = 5

    def __init__(
        self,
        plugin_config: Optional[PluginConfig] = None,
        *,
        hook_timeout: Optional[float] = None,
        failure_threshold: Optional[int] = None,
        disable_threshold: Optional[int] = None,
    ) -> None:
        self.pm = pluggy.PluginManager("py_code_agent")
        # Register all hook specifications
        self.pm.add_hookspecs(hooks.ToolHooks)
        self.pm.add_hookspecs(hooks.AgentHooks)
        self.pm.add_hookspecs(hooks.StreamingHooks)
        self.pm.add_hookspecs(hooks.SessionHooks)
        self.pm.add_hookspecs(hooks.ModelHooks)
        self.pm.add_hookspecs(hooks.TurnHooks)
        self.pm.add_hookspecs(hooks.ExtensionHooks)

        self._plugin_names: List[str] = []
        self._health: Dict[str, PluginHealth] = {}
        self._loaded_modules: Dict[str, Any] = {}
        self._plugin_config = plugin_config or PluginConfig()
        # Per-plugin AiAutoRepair instances (Layer 1-4 fixes).
        self._auto_repairers: Dict[str, AiAutoRepair] = {}

        # Hardening config.
        self._hook_timeout: float = hook_timeout or self.DEFAULT_HOOK_TIMEOUT
        self._failure_threshold: int = failure_threshold or self.DEFAULT_FAILURE_THRESHOLD
        self._disable_threshold: int = disable_threshold or self.DEFAULT_DISABLE_THRESHOLD

        # Core module names that plugins MUST NOT shadow.
        self._protected_prefixes: Set[str] = {
            "py_code_agent",
        }
        # Snapshot of core modules before any plugin loads.
        self._protected_modules: Set[str] = self._snapshot_protected_modules()

        # Thread pool for hook timeouts.
        self._executor: ThreadPoolExecutor = ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="plugin-hook-"
        )

        self._agent_ref: Any = None

    # ------------------------------------------------------------------
    # Agent reference (for plugins that need to call agent.run for subtasks)
    # ------------------------------------------------------------------

    def set_agent(self, agent: Any) -> None:
        """Pass agent reference to plugins that need it.

        Plugins can access agent.llm, agent.tools, agent.run() etc.
        Called by Agent._setup_plugins() after load_plugins().
        """
        self._agent_ref = agent
        # Notify plugins that support set_agent
        for name in list(self._plugin_names):
            plugin_instance = self.pm.get_plugin(name)
            if plugin_instance is not None and hasattr(plugin_instance, "set_agent"):
                try:
                    plugin_instance.set_agent(agent)
                except BaseException:
                    logger.warning(
                        "Plugin %s.set_agent() raised — suppressed", name
                    )

    # ------------------------------------------------------------------
    # Module protection
    # ------------------------------------------------------------------

    def _snapshot_protected_modules(self) -> Set[str]:
        """Capture the set of core modules before plugins run."""
        return {
            name
            for name in sys.modules
            if any(name.startswith(p) for p in self._protected_prefixes)
        }

    def _restore_protected_modules(self) -> None:
        """Restore core modules that a plugin may have accidentally replaced."""
        protected = self._protected_modules
        for name in list(sys.modules):
            if name in protected and not name.startswith("py_code_agent.plugins"):
                try:
                    del sys.modules[name]
                except KeyError:
                    pass

    # ------------------------------------------------------------------
    # Error classification
    # ------------------------------------------------------------------

    def _is_fatal(self, error: BaseException) -> bool:
        """Return True if this exception MUST NOT propagate from a plugin."""
        return isinstance(error, _FATAL_PLUGIN_EXCEPTIONS)

    def _is_unrecoverable(self, error: BaseException) -> bool:
        """Return True if this indicates a plugin bug that should disable it."""
        return isinstance(error, _UNRECOVERABLE_PLUGIN_EXCEPTIONS)

    # ------------------------------------------------------------------
    # Core failure tracking with immediate-disable for fatal errors
    # ------------------------------------------------------------------

    def _track_failure(self, name: str, error: Any, *, immediate: bool = False) -> None:
        """Track a plugin failure, optionally disabling it immediately.

        Args:
            name: plugin name
            error: the exception or error message
            immediate: if True, disable the plugin right now (fatal/unrecoverable)
        """
        if name not in self._health:
            self._health[name] = PluginHealth(name=name)
        h = self._health[name]

        h.failure_count += 1
        h.last_error = str(error)[:200]

        if immediate or h.failure_count >= self._disable_threshold:
            h.disabled = True
            h.disabled_reason = (
                f"fatal: {type(error).__name__}" if immediate else
                f"exceeded failure threshold ({h.failure_count})"
            )
            logger.error(
                "Plugin %s disabled immediately: %s",
                name,
                error,
            )
        else:
            logger.warning(
                "Plugin %s hook failed [%d/%d]: %s",
                name,
                h.failure_count,
                self._disable_threshold,
                error,
            )

    # ------------------------------------------------------------------
    # Auto-repair helpers
    # ------------------------------------------------------------------

    def _get_auto_repairer(self, name: str) -> Optional[AiAutoRepair]:
        """Get or create an AiAutoRepair instance for a plugin."""
        if name in self._auto_repairers:
            return self._auto_repairers[name]
        plugin_instance = self.pm.get_plugin(name)
        if plugin_instance is None:
            return None
        ar = AiAutoRepair(name, plugin_instance)
        self._auto_repairers[name] = ar
        return ar

    def _handle_hook_error(
        self, name: str, hook_name: str, e: BaseException
    ) -> bool:
        """Handle a non-timeout hook error. Returns True if handled (error consumed), False to count failure."""
        ar = self._get_auto_repairer(name)
        if ar is not None:
            ar._last_error = e

        if self._is_fatal(e):
            logger.critical(
                "Plugin %s raised FATAL '%s' in '%s' — suppressed: %s",
                name,
                type(e).__name__,
                hook_name,
                e,
            )
            self._track_failure(name, f"fatal: {type(e).__name__}: {e}", immediate=True)
            return True

        if self._is_unrecoverable(e):
            logger.error(
                "Plugin %s raised '%s' in '%s' — attempting fix: %s",
                name,
                type(e).__name__,
                hook_name,
                e,
            )
            self._track_failure(name, f"{type(e).__name__}: {e}", immediate=True)
            return True

        logger.debug(
            "Plugin %s hook '%s' raised %s: %s",
            name,
            hook_name,
            type(e).__name__,
            e,
        )
        self._track_failure(name, f"{type(e).__name__}: {e}")
        return False

    # ------------------------------------------------------------------
    # Hook execution with timeout isolation
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Plugin loading (all protected)
    # ------------------------------------------------------------------

    def load_plugins(self, plugin_dirs: Optional[List[Path]] = None) -> None:
        self._load_from_entry_points()
        if plugin_dirs:
            for plugin_dir in plugin_dirs:
                self._load_from_dir(plugin_dir)
        
        self._load_dependencies(plugin_dirs or [])

    def _load_dependencies(self, plugin_dirs: List[Path]) -> None:
        loaded = set(self._plugin_names)
        
        for name in list(self._plugin_names):
            plugin = self.pm.get_plugin(name)
            if plugin is None:
                continue
            
            docstring = getattr(plugin.__class__, "__doc__", "") or ""
            
            deps = []
            dep_section = re.search(r"Dependencies:\s*\n((?:\s*-.*\n)+)", docstring, re.MULTILINE)
            if dep_section:
                for line in dep_section.group(1).split("\n"):
                    if not line.strip().startswith("-"):
                        continue
                    match = re.search(r"\(file:([\w-]+)\)", line)
                    if match:
                        deps.append(f"file:{match.group(1)}")
            
            for dep_name in deps:
                if dep_name in loaded:
                    continue
                
                logger.info(f"[Plugin] Auto-loading dependency: {dep_name} (required by {name})")
                
                if plugin_dirs:
                    for plugin_dir in plugin_dirs:
                        if not plugin_dir.exists():
                            continue
                        for py_file in plugin_dir.glob("*.py"):
                            if py_file.name.startswith("_"):
                                continue
                            canonical = py_file.stem
                            if canonical.endswith("_plugin"):
                                canonical = canonical.removesuffix("_plugin")
                            file_name = f"file:{canonical}"
                            
                            if file_name == dep_name:
                                self._load_plugin_file(py_file)
                                loaded.add(dep_name)
                                break



    def enable_plugin(self, name: str) -> bool:
        """Dynamically enable a plugin by name."""
        if name.startswith("file:"):
            canonical = name[5:]
            full_name = name
        else:
            canonical = name
            full_name = f"file:{name}"
        
        if full_name in self._plugin_names and self._is_enabled(full_name):
            logger.info(f"[Plugin] {full_name} already enabled")
            return True
        
        if full_name not in self._plugin_names:
            builtin_dir = Path(__file__).parent.parent.parent / "plugins" / "builtin"
            if builtin_dir.exists():
                plugin_file = builtin_dir / f"{canonical}_plugin.py"
                if plugin_file.exists():
                    self._load_plugin_file(plugin_file)
        
        if full_name in self._plugin_names:
            if self._plugin_config.enabled and full_name not in self._plugin_config.enabled:
                self._plugin_config.enabled.append(full_name)
            if full_name in self._plugin_config.disabled:
                self._plugin_config.disabled.remove(full_name)
            
            logger.info(f"[Plugin] Enabled: {full_name}")
            return True
        else:
            logger.warning(f"[Plugin] Failed to enable {full_name}: not found")
            return False

    def _is_enabled(self, name: str) -> bool:
        return self._plugin_config.is_enabled(name)

    def _track_success(self, name: str) -> None:
        h = self._health.get(name)
        if h:
            h.success_count += 1
            h.last_success = datetime.now()

    def _load_from_entry_points(self) -> None:
        if sys.version_info >= (3, 10):
            from importlib.metadata import entry_points
        else:
            from importlib_metadata import entry_points

        eps = entry_points()
        if hasattr(eps, "select"):
            plugin_eps = eps.select(group="py_code_agent.plugins")
        else:
            plugin_eps = eps.get("py_code_agent.plugins", [])  # type: ignore[union-attr]

        for ep in plugin_eps:
            self._load_entry_point(ep)

    def _load_entry_point(self, ep: Any) -> None:
        name = ep.name
        try:
            plugin = ep.load()
            plugin_instance = plugin() if isinstance(plugin, type) else plugin
            self._register_plugin(name, plugin_instance)
        except ImportError as e:
            ar = AiAutoRepair(name, None)
            if ar.fix_import_error(e):
                try:
                    plugin = ep.load()
                    plugin_instance = plugin() if isinstance(plugin, type) else plugin
                    self._register_plugin(name, plugin_instance)
                    return
                except ImportError:
                    pass
            logger.warning("Failed to load entry-point plugin %s: %s", name, e)
            self._track_failure(name, traceback.format_exc())
        except BaseException as e:
            if self._is_fatal(e):
                logger.critical(
                    "Entry-point plugin %s raised FATAL '%s' during load — suppressed: %s",
                    name,
                    type(e).__name__,
                    e,
                )
            else:
                logger.warning("Failed to load entry-point plugin %s: %s", name, e)
            self._track_failure(name, traceback.format_exc())

    def _load_from_dir(self, plugin_dir: Path) -> None:
        if not plugin_dir.exists():
            return

        for py_file in plugin_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            self._load_plugin_file(py_file)

    def _load_plugin_file(self, py_file: Path) -> None:
        # Canonical name: strip common _plugin suffix for consistency with CLI
        # (e.g. log_plugin.py → file:log, soul_plugin.py → file:soul)
        canonical = py_file.stem
        if canonical.endswith("_plugin"):
            canonical = canonical.removesuffix("_plugin")
        name = f"file:{canonical}"
        module_name = f"py_code_agent_plugins.{py_file.stem}"

        repo_root = str(py_file.parent.parent.parent)
        for p in (repo_root, f"{repo_root}/src"):
            if p not in sys.path:
                sys.path.insert(0, p)

        try:
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if not spec or not spec.loader:
                return

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            self._loaded_modules[module_name] = module

            found = 0
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and attr is not PluginPlugin and hasattr(
                    attr, "register_tools"
                ):
                    try:
                        instance = attr()
                        self._register_plugin(name, instance)
                        found += 1
                    except BaseException as e:
                        if self._is_fatal(e):
                            logger.critical(
                                "Plugin %s raised FATAL '%s' during instantiation — suppressed: %s",
                                attr_name,
                                type(e).__name__,
                                e,
                            )
                        else:
                            logger.warning(
                                "Failed to instantiate plugin %s in %s: %s",
                                attr_name,
                                py_file,
                                e,
                            )
                        self._track_failure(
                            name,
                            traceback.format_exc(),
                            immediate=self._is_fatal(e),
                        )

            if found == 0:
                logger.debug("No plugin classes found in %s", py_file)

        except ImportError as e:
            ar = AiAutoRepair(name, None)
            if ar.fix_import_error(e):
                self._load_plugin_file(py_file)
                return
            logger.warning("Failed to load plugin file %s: %s", py_file, e)
            self._track_failure(name, traceback.format_exc())

        except BaseException as e:
            if self._is_fatal(e):
                logger.critical(
                    "Plugin file %s raised FATAL '%s' during load — suppressed: %s",
                    py_file,
                    type(e).__name__,
                    e,
                )
                self._track_failure(name, traceback.format_exc(), immediate=True)
            else:
                logger.warning("Failed to load plugin file %s: %s", py_file, e)
                self._track_failure(name, traceback.format_exc())

    def _register_plugin(self, name: str, plugin: Any) -> None:
        try:
            self.pm.register(plugin, name=name)
            self._plugin_names.append(name)
            self._health[name] = PluginHealth(name=name, loaded_at=datetime.now())
            logger.info("Loaded plugin: %s", name)
        except BaseException as e:
            if self._is_fatal(e):
                logger.critical(
                    "Plugin %s raised FATAL '%s' during registration — suppressed: %s",
                    name,
                    type(e).__name__,
                    e,
                )
                self._track_failure(name, traceback.format_exc(), immediate=True)
            elif "already registered" not in str(e).lower():
                logger.warning("Failed to register plugin %s: %s", name, e)
                self._track_failure(name, traceback.format_exc())

    # ------------------------------------------------------------------
    # Tool registration (fully protected — never crashes core startup)
    # ------------------------------------------------------------------

    def register_tools(self) -> List[BaseTool]:
        """Register tools from all healthy plugins. Errors are fully isolated."""
        tools: List[BaseTool] = []
        # Get plugin instances directly from pluggy's registry.
        plugins_dict = getattr(self.pm, "_plugins", {})

        for name in list(self._plugin_names):
            if not self._is_enabled(name):
                continue
            h = self._health.get(name)
            if h is None or h.disabled:
                continue

            plugin_instance = self.pm.get_plugin(name)
            if plugin_instance is None:
                continue

            # Call register_tools directly on the plugin instance.
            # Do NOT use self.pm.hook.register_tools() — that calls ALL plugins'
            # hooks and returns results from every plugin (not just the named one).
            try:
                if hasattr(plugin_instance, "register_tools"):
                    result = plugin_instance.register_tools()
                    if result:
                        tools.extend(result)
                self._track_success(name)
            except TimeoutExpired:
                logger.error(
                    "Plugin %s timed out during register_tools() — disabling", name
                )
                self._track_failure(
                    name, "timeout during register_tools()", immediate=True
                )
            except BaseException as e:
                if self._is_fatal(e):
                    logger.critical(
                        "Plugin %s raised FATAL '%s' during register_tools() — "
                        "suppressed: %s",
                        name,
                        type(e).__name__,
                        e,
                    )
                    self._track_failure(name, e, immediate=True)
                elif self._is_unrecoverable(e):
                    logger.error(
                        "Plugin %s raised unrecoverable '%s' during register_tools() "
                        "— disabling: %s",
                        name,
                        type(e).__name__,
                        e,
                    )
                    self._track_failure(name, e, immediate=True)
                else:
                    logger.warning(
                        "Plugin %s raised '%s' during register_tools(): %s",
                        name,
                        type(e).__name__,
                        e,
                    )
                    self._track_failure(name, e)
        return tools

    # ------------------------------------------------------------------
    # Hook callers — all use _safe_hook_call for isolation
    # ------------------------------------------------------------------

    def call_before_tool_execute(self, tool_name: str, arguments: Dict[str, Any]) -> None:
        self._call_hooks_for_enabled(
            "before_tool_execute",
            self.pm.hook.before_tool_execute,
            tool_name=tool_name,
            arguments=arguments,
        )

    def call_after_tool_execute(
        self, tool_name: str, arguments: Dict[str, Any], result: Any
    ) -> None:
        self._call_hooks_for_enabled(
            "after_tool_execute",
            self.pm.hook.after_tool_execute,
            tool_name=tool_name,
            arguments=arguments,
            result=result,
        )

    def call_enhance_tool_error(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        error_info: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Call enhance_tool_error on all enabled plugins, return first non-None result.

        Plugins can classify tool errors and return structured enhancement with
        diagnosis and fix suggestions. First plugin that returns a non-None result
        wins — plugins are checked in priority order.
        """
        return self._call_hooks_first_valid(
            "enhance_tool_error",
            self.pm.hook.enhance_tool_error,
            tool_name=tool_name,
            arguments=arguments,
            error_info=error_info,
        )

    def call_on_agent_start(self, input: str) -> None:
        self._call_hooks_for_enabled(
            "on_agent_start",
            self.pm.hook.on_agent_start,
            input=input,
        )

    def call_on_agent_end(self) -> None:
        self._call_hooks_for_enabled("on_agent_end", self.pm.hook.on_agent_end)

    def call_on_llm_call(
        self, messages: Any, tools: List[Dict[str, Any]]
    ) -> None:
        # Convert Message objects to dicts for plugins that expect List[Dict]
        msgs_as_dicts = []
        for m in messages:
            if hasattr(m, "to_dict"):
                msgs_as_dicts.append(m.to_dict())
            elif hasattr(m, "role") and hasattr(m, "content"):
                d = {"role": m.role, "content": m.content}
                if hasattr(m, "tool_calls"):
                    d["tool_calls"] = m.tool_calls
                if hasattr(m, "tool_call_id"):
                    d["tool_call_id"] = m.tool_call_id
                msgs_as_dicts.append(d)
            elif isinstance(m, dict):
                msgs_as_dicts.append(m)
        self._call_hooks_for_enabled(
            "on_llm_call",
            self.pm.hook.on_llm_call,
            messages=msgs_as_dicts,
            tools=tools,
        )

    def call_on_llm_response(self, response: Any) -> None:
        self._call_hooks_for_enabled(
            "on_llm_response",
            self.pm.hook.on_llm_response,
            response=response,
        )

    def call_get_system_prompt(self) -> str:
        """Aggregate system prompt contributions from all enabled plugins.

        Each plugin's get_system_prompt() is called and wrapped with structured
        markers so the LLM can identify the source. Format:
          <!-- [PLUGIN:plugin_name] -->
          ...content...
          <!-- [/PLUGIN:plugin_name] -->
        """
        parts: List[str] = []
        enabled_names = [
            name
            for name in list(self._plugin_names)
            if self._is_enabled(name)
            and self._health.get(name, PluginHealth(name=name)).is_healthy
        ]
        for name in enabled_names:
            plugin_instance = self.pm.get_plugin(name)
            if plugin_instance is None:
                continue
            if not hasattr(plugin_instance, "get_system_prompt"):
                continue
            h = self._health.get(name)
            if h and h.disabled:
                continue
            try:
                result = plugin_instance.get_system_prompt()
                if result and isinstance(result, str) and result.strip():
                    plugin_tag = name.removeprefix("file:").replace(":", "_")
                    parts.append(
                        f"<!-- [PLUGIN:{plugin_tag}] -->\n{result.strip()}\n<!-- [/PLUGIN:{plugin_tag}] -->"
                    )
            except BaseException as e:
                if not self._is_fatal(e) and not self._is_unrecoverable(e):
                    logger.warning(
                        "Plugin %s.get_system_prompt() raised '%s': %s",
                        name, type(e).__name__, e,
                    )
                self._track_failure(name, f"{type(e).__name__}: {e}")
        return "\n\n".join(parts)

    def call_on_plugin_heartbeat(self, event: str, data: Dict[str, Any]) -> None:
        """Emit unified plugin heartbeat event to all enabled plugins.

        This is the central hub for plugin heartbeat events. All plugins that
        implement on_plugin_heartbeat will receive this event (typically just
        HeartbeatPlugin for aggregation).

        Args:
            event: Specific event type (e.g., "scored", "started", "completed")
            data: Event data including plugin_name, plugin_id, and event-specific fields
        """
        self._call_hooks_for_enabled(
            "on_plugin_heartbeat",
            self.pm.hook.on_plugin_heartbeat,
            event=event,
            data=data,
        )

    def _safe_hook_call(
        self,
        name: str,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Call a plugin hook for a single named plugin with full error isolation.

        Note: for multi-plugin hooks (call_on_agent_start, etc.), prefer
        _call_hooks_for_enabled() which calls the HookCaller once for all plugins.
        This method calls the hook for a single plugin — use when the HookCaller
        must be invoked per-plugin (e.g. register_tools via pm.get_plugin).
        """
        h = self._health.get(name)
        if h and h.disabled:
            return

        timeout = self._hook_timeout
        hook_name = getattr(func, "name", None) or getattr(func, "__name__", str(func))

        def _call() -> Any:
            try:
                return func(*args, **kwargs)
            finally:
                self._restore_protected_modules()

        def _do_call() -> bool:
            try:
                if timeout > 0:
                    future = self._executor.submit(_call)
                    future.result(timeout=timeout)
                else:
                    _call()
                self._track_success(name)
                return True
            except TimeoutExpired:
                self._track_failure(
                    name, f"timeout after {timeout}s ({hook_name})", immediate=True
                )
                return False
            except BaseException as e:
                return self._handle_hook_error(name, hook_name, e)

        if _do_call():
            return

        ar = self._get_auto_repairer(name)
        if ar is None:
            return

        last_err = getattr(ar, "_last_error", None)
        is_attr_err = isinstance(last_err, AttributeError)
        fixed = ar.wrap_method(hook_name, func) or (
            is_attr_err and ar.inject_stub(hook_name)
        )

        if fixed:
            logger.info(
                "[AiAutoRepair] Retrying '%s' hook '%s' after fix", name, hook_name
            )
            _do_call()

    def _call_hooks_for_enabled(
        self, hook_name: str, hook_caller: Any, **kwargs: Any
    ) -> None:
        """Call a hook for all enabled/healthy plugins exactly once.

        Note: pluggy's HookCaller invokes ALL registered hook implementations
        in a single call. We call it once and track success for each enabled
        plugin. Disabled/unhealthy plugins are skipped via pluggy's blocking.
        """
        enabled_names = [
            name
            for name in list(self._plugin_names)
            if self._is_enabled(name)
            and self._health.get(name, PluginHealth(name=name)).is_healthy
        ]
        if not enabled_names:
            return

        def _call() -> Any:
            try:
                return hook_caller(**kwargs)
            finally:
                self._restore_protected_modules()

        timeout = self._hook_timeout

        def _do_call() -> bool:
            try:
                if timeout > 0:
                    future = self._executor.submit(_call)
                    future.result(timeout=timeout)
                else:
                    _call()
                for name in enabled_names:
                    self._track_success(name)
                return True
            except TimeoutExpired:
                for name in enabled_names:
                    self._track_failure(
                        name,
                        f"timeout after {timeout}s ({hook_name})",
                        immediate=True,
                    )
                return False
            except BaseException as e:
                for name in enabled_names:
                    self._handle_hook_error(name, hook_name, e)
                return False

        _do_call()

    def _call_hooks_first_valid(
        self, hook_name: str, hook_caller: Any, **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        """Call a hook for enabled plugins, return first non-None result.

        Unlike _call_hooks_for_enabled which calls all plugins, this stops at
        the first plugin that returns a non-None result. Used for error
        enhancement where we want the best-matching plugin's diagnosis.

        For enhance_tool_error: plugins are sorted by priority (lower = first).
        """
        enabled_names = [
            name
            for name in list(self._plugin_names)
            if self._is_enabled(name)
            and self._health.get(name, PluginHealth(name=name)).is_healthy
        ]
        if not enabled_names:
            return None

        if hook_name == "enhance_tool_error":
            enabled_names = self._sort_by_priority(enabled_names, "enhance_tool_error_priority")

        for name in enabled_names:
            plugin = self.pm.get_plugin(name)
            if plugin is None:
                continue
            impl = getattr(plugin, hook_name, None)
            if not callable(impl):
                continue
            try:
                result = impl(**kwargs)
                if result is not None and result != {}:
                    self._track_success(name)
                    return result
            except Exception as e:
                self._handle_hook_error(name, hook_name, e)

        return None

    def _sort_by_priority(self, plugin_names: List[str], priority_attr: str) -> List[str]:
        """Sort plugins by priority attribute (lower = higher priority)."""
        def get_priority(name: str) -> int:
            plugin = self.pm.get_plugin(name)
            if plugin is None:
                return 100
            priority_fn = getattr(plugin, priority_attr, None)
            if callable(priority_fn):
                try:
                    return priority_fn()
                except Exception:
                    return 100
            return 100

        return sorted(plugin_names, key=get_priority)

    # ------------------------------------------------------------------
    # Self-healing
    # ------------------------------------------------------------------

    def heal_plugin(self, name: str) -> bool:
        h = self._health.get(name)
        if not h:
            return False
        h.failure_count = 0
        h.disabled = False
        h.last_error = None
        h.disabled_reason = None
        logger.info("Plugin %s healed (reset failure count)", name)
        return True

    def heal_all(self) -> int:
        count = 0
        for name in self._health:
            if self._health[name].failure_count > 0:
                self.heal_plugin(name)
                count += 1
        return count

    def disable_plugin(self, name: str, reason: str = "manual") -> bool:
        """Explicitly disable a plugin with a reason."""
        h = self._health.get(name)
        if not h:
            return False
        h.disabled = True
        h.disabled_reason = reason
        logger.info("Plugin %s disabled (%s)", name, reason)
        return True

    def get_health_report(self) -> Dict[str, Any]:
        return {
            "total_loaded": len(self._plugin_names),
            "healthy": sum(1 for h in self._health.values() if h.is_healthy),
            "degraded": sum(
                1 for h in self._health.values()
                if not h.disabled and h.failure_count > 0
            ),
            "disabled": sum(1 for h in self._health.values() if h.disabled),
            "hook_timeout": self._hook_timeout,
            "failure_threshold": self._failure_threshold,
            "disable_threshold": self._disable_threshold,
            "plugins": {
                name: {
                    "status": h.status,
                    "disabled_reason": h.disabled_reason,
                    "success_count": h.success_count,
                    "failure_count": h.failure_count,
                    "last_error": h.last_error,
                }
                for name, h in self._health.items()
            },
        }

    @property
    def loaded_plugins(self) -> List[str]:
        return list(self._plugin_names)

    # ------------------------------------------------------------------
    # Startup health check & auto-repair
    # ------------------------------------------------------------------

    def check_and_repair(self) -> Dict[str, Any]:
        """Run a full health check and attempt auto-repair on startup.

        Strategy:
        1. For plugins with transient errors (failure_count > 0 but not
           disabled): call heal_plugin() to reset counts.
        2. For disabled plugins with "exceeded failure threshold" reason
           (not fatal/unrecoverable): attempt reload.
        3. Return a detailed report for logging / UI display.

        Returns:
            Dict with repair statistics and per-plugin outcomes.
        """
        report: Dict[str, Any] = {
            "total": len(self._health),
            "healed": [],
            "reloaded": [],
            "still_disabled": [],
            "already_healthy": [],
        }

        for name, h in list(self._health.items()):
            if h.disabled:
                # Don't auto-repair fatal/unrecoverable disables.
                if h.disabled_reason and any(
                    r.startswith("fatal") for r in [h.disabled_reason]
                ):
                    report["still_disabled"].append(
                        {"name": name, "reason": h.disabled_reason, "action": "skip"}
                    )
                    continue

                # Try to reload disabled plugins.
                reloaded = self.reload_plugin(name)
                if reloaded:
                    report["reloaded"].append(
                        {
                            "name": name,
                            "previous_reason": h.disabled_reason,
                            "action": "reloaded",
                        }
                    )
                else:
                    report["still_disabled"].append(
                        {"name": name, "reason": h.disabled_reason, "action": "failed"}
                    )
            elif h.failure_count > 0 and h.is_healthy:
                # Degraded but still running — reset counts.
                self.heal_plugin(name)
                report["healed"].append(
                    {
                        "name": name,
                        "previous_failures": h.failure_count,
                        "action": "healed",
                    }
                )
            elif h.is_healthy and h.failure_count == 0:
                report["already_healthy"].append(name)

        logger.info(
            "Plugin health check: %d healthy, %d healed, %d reloaded, %d still disabled",
            len(report["already_healthy"]),
            len(report["healed"]),
            len(report["reloaded"]),
            len(report["still_disabled"]),
        )
        return report

    def reload_plugin(self, name: str) -> bool:
        """Attempt to reload a disabled plugin by name.

        Currently supports file-based plugins (name starts with "file:").
        For entry-point plugins, only re-enables if the previous error was
        transient (not fatal/unrecoverable).

        Returns:
            True if the plugin was successfully reloaded and re-registered.
        """
        h = self._health.get(name)
        if h is None:
            return False

        # Check if the error was fatal — don't auto-reload.
        if h.disabled_reason and h.disabled_reason.startswith("fatal"):
            logger.debug(
                "Plugin %s has a fatal disable reason, skipping reload: %s",
                name,
                h.disabled_reason,
            )
            return False

        # Handle file-based plugins.
        if name.startswith("file:"):
            stem = name.split(":", 1)[1]
            # Find the plugin source file.
            plugin_file = self._find_plugin_file(stem)
            if plugin_file and plugin_file.exists():
                return self._reload_plugin_from_file(name, plugin_file)
            else:
                logger.warning(
                    "Cannot reload %s: plugin source file not found", name
                )
                return False

        # Entry-point plugin: re-enable and clear health.
        self.heal_plugin(name)
        logger.info("Re-enabled entry-point plugin %s (transient error)", name)
        return True

    def _find_plugin_file(self, stem: str) -> Optional[Path]:
        """Find the plugin source .py file for a file-based plugin name."""
        # Search common plugin directories.
        search_dirs: List[Path] = []
        # Built-in plugins directory (repo/plugins/builtin/).
        search_dirs.append(Path(__file__).parent.parent.parent.parent / "plugins" / "builtin")
        # Local project plugins (.py-code-agent/plugins/).
        local_plugins = Path.cwd() / ".py-code-agent" / "plugins"
        if local_plugins.exists():
            search_dirs.append(local_plugins)
        # Global user plugins (~/.config/py-code-agent/plugins/).
        global_plugins = Path.home() / ".config" / "py-code-agent" / "plugins"
        if global_plugins.exists():
            search_dirs.append(global_plugins)

        for search_dir in search_dirs:
            if not search_dir.exists():
                continue
            for py_file in search_dir.glob("*.py"):
                # Match canonical name (stripped _plugin) or original stem
                canonical = py_file.stem
                if canonical.endswith("_plugin"):
                    canonical = canonical.removesuffix("_plugin")
                if canonical == stem or py_file.stem == stem:
                    return py_file
        return None

    def _reload_plugin_from_file(self, name: str, py_file: Path) -> bool:
        """Reload a single file-based plugin, replacing the old registration."""
        module_name = f"py_code_agent_plugins.{py_file.stem}"

        # Remove old registration from pluggy.
        # Unregister by removing from pm registry — pluggy doesn't expose
        # a public unregister API, so we mark disabled and skip in hooks.
        # Instead, re-instantiate and register under same name (pluggy allows
        # re-registration of the same name as update).
        old_health = self._health.get(name)
        self._health.pop(name, None)
        if name in self._plugin_names:
            self._plugin_names.remove(name)

        try:
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if not spec or not spec.loader:
                return False

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            self._loaded_modules[module_name] = module

            found = 0
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and hasattr(attr, "register_tools"):
                    instance = attr()
                    self.pm.register(instance, name=name)
                    self._plugin_names.append(name)
                    self._health[name] = PluginHealth(name=name, loaded_at=datetime.now())
                    found += 1
                    logger.info("Reloaded plugin %s from %s", name, py_file)
                    break  # Only take the first matching class.

            if found == 0:
                return False
            return True

        except BaseException as e:
            # Reload failed — restore previous health state.
            if old_health:
                self._health[name] = old_health
                if name not in self._plugin_names:
                    self._plugin_names.append(name)
            logger.warning("Failed to reload plugin %s: %s", name, e)
            return False

    def shutdown(self) -> None:
        """Gracefully shut down the plugin executor. Call on application exit."""
        self._executor.shutdown(wait=False)
        logger.debug("Plugin executor shut down")


class LoadPluginsTool(BaseTool):
    """Load and enable plugins dynamically."""

    def __init__(self, plugin_manager: PluginManager):
        self.plugin_manager = plugin_manager

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="load_plugins",
            description="Load and enable plugins by name. Use when you need tools from a plugin that isn't loaded yet.",
            parameters=[
                ToolParameter(
                    name="plugins",
                    type=ToolParameterType.STRING,
                    description="Comma-separated list of plugin names to load (e.g., 'context,plan')",
                    required=True
                ),
                ToolParameter(
                    name="reason",
                    type=ToolParameterType.STRING,
                    description="Why you need these plugins",
                    required=False
                )
            ],
        )

    async def execute(self, plugins: str = "", reason: str = "", **kwargs: Any) -> ToolResult:
        plugin_list = [p.strip() for p in plugins.split(",") if p.strip()]
        loaded = []
        failed = []
        
        for plugin_name in plugin_list:
            full_name = f"file:{plugin_name}"
            needs_enable = full_name not in self.plugin_manager._plugin_names or \
                          not self.plugin_manager._is_enabled(full_name)
            if needs_enable:
                if self.plugin_manager.enable_plugin(full_name):
                    loaded.append(plugin_name)
                else:
                    failed.append(plugin_name)
            else:
                loaded.append(f"{plugin_name} (already loaded)")
        
        if failed:
            return ToolResult(
                success=False,
                data={"loaded": loaded, "failed": failed},
                error=f"Failed to load: {failed}",
                summary=f"Loaded: {loaded}, Failed: {failed}"
            )
        
        return ToolResult(
            success=True,
            data={"loaded": loaded},
            summary=f"Loaded {len(loaded)} plugins: {loaded}"
        )


class PluginPlugin:
    _pm_instance: Optional["PluginManager"] = None

    @classmethod
    def set_plugin_manager(cls, pm: "PluginManager") -> None:
        cls._pm_instance = pm

    @hooks.hookimpl
    def register_tools(self) -> List[BaseTool]:
        if self._pm_instance:
            return [LoadPluginsTool(self._pm_instance)]
        return []
