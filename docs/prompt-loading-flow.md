# Agent 提示词加载流程与说明

本文档详细说明 Py Code Agent 中 Agent 提示词（Prompt）的加载机制与架构设计。

---

## 1. 核心架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                      Agent.run()                            │
│  _prepare_messages() → 构建完整的 system prompt              │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              Base System Prompt (硬编码)                     │
│  ├── ReAct 模式提示 (启用时)                                  │
│  └── 标准模式提示 (禁用时)                                    │
│  + Tool Failure Self-Recovery 规则                           │
│  + Task Completion 规则                                     │
└─────────────────────┬───────────────────────────────────────┘
                      │ + "\n\n"
                      ▼
┌─────────────────────────────────────────────────────────────┐
│        Plugin System Prompt (动态聚合)                       │
│  plugin_manager.call_get_system_prompt()                    │
│  └─ 遍历所有启用的插件，调用 get_system_prompt()              │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                    Final System Message                     │
│  [Base] + "\n\n" + [Plugin Prompts]                        │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Base Prompt (核心层)

### 2.1 位置
`src/py_code_agent/core/agent.py` → `_prepare_messages()` 方法

### 2.2 ReAct 模式提示 (启用时)

```python
base_prompt = """You are a helpful AI coding assistant using the ReAct (Reasoning + Acting) pattern.

Think step by step before taking actions. Follow this format:
Thought: [Your reasoning about what to do next]
Action: [The tool call or your final answer]
Observation: [The result of the action]

If you need to use a tool, format it as: tool_name({"arg": "value"})
If you're done, put your final answer in Action without any tool call.

## Tool Failure Self-Recovery
When a tool call fails (returns an error), do NOT immediately report failure.
Diagnose the root cause and attempt recovery before giving up:

1. **Missing dependency** — 'command not found', 'module not found'
   → Install the missing tool/runtime, then retry the original tool call
2. **Wrong tool used** — output is wrong format, skill workflow was skipped
   → Re-read the relevant skill and follow its workflow
3. **Partial failure** — some steps worked but final output is wrong
   → Fix only the failing step, preserve work from successful steps
4. **Permission/environment issue** — sandbox restrictions, path errors
   → Use execute_bash to find valid paths

IMPORTANT: You have multiple turns. Use them to recover from failures.

## Task Completion
When you believe the original task is complete, you MUST call task_done to verify.
This is the ONLY way to end the session. Do not just stop responding.
"""
```

### 2.3 标准模式提示 (禁用时)

```python
base_prompt = """You are a helpful AI coding assistant. You have access to tools for file operations,
bash commands, and more. Use these tools when needed to help the user.

## Tool Failure Self-Recovery
When a tool call fails, diagnose the root cause and attempt recovery:
1. Missing dependency → install it, then retry
2. Wrong tool used → re-read relevant skill, follow its workflow
3. Partial failure → fix only the failing step, preserve successful work
4. Permission issue → find valid paths, adjust tool arguments

IMPORTANT: You have multiple turns. Use them to recover — do not report failure prematurely.

## Task Completion
When you believe the task is done, you MUST call task_done to verify.
This is the ONLY way to end the session. Do not just stop responding.
"""
```

---

## 3. Plugin Hook 系统

### 3.1 Hook 接口定义

**位置**: `src/py_code_agent/plugins/hooks.py`

```python
class AgentHooks:
    """Agent lifecycle hooks."""

    @hookspec
    def get_system_prompt(self) -> str:
        """Return additional system prompt content to inject into the agent.

        Plugins can contribute context-specific guidance, role definitions, or
        behavioral instructions. Content is appended to the base system prompt.
        Return empty string if no contribution.
        """
```

### 3.2 现有 Hook 类型

| Hook | 用途 |
|------|------|
| `register_tools()` | 注册工具 |
| `on_agent_start()` | Agent 开始处理输入 |
| `on_agent_end()` | Agent 完成处理 |
| `on_llm_call()` | LLM 调用前 |
| `on_llm_response()` | LLM 响应后 |
| `get_system_prompt()` | 返回额外的系统提示词 |
| `enhance_tool_error()` | 增强错误信息 |
| `before_tool_execute()` | 工具执行前 |
| `after_tool_execute()` | 工具执行后 |

---

## 4. Plugin Prompt 聚合机制

### 4.1 位置
`src/py_code_agent/plugins/manager.py` → `call_get_system_prompt()`

### 4.2 实现逻辑

```python
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
            # 错误处理...
            self._track_failure(name, f"{type(e).__name__}: {e}")
    return "\n\n".join(parts)
```

### 4.3 特点

- **遍历所有启用且健康的插件**
- **包装为 XML 标记** `<!-- [PLUGIN:xxx] -->` 便于 LLM 识别来源
- **按注册顺序** 拼接
- **错误隔离**：单个插件失败不影响整体

---

## 5. 内置插件的 System Prompt

| 插件 | 路径 | Prompt 内容 |
|------|------|------------|
| **PlanPlugin** | `plugins/builtin/plan_plugin.py:1018` | MANDATORY 规划规则 |
| **SkillsPlugin** | `plugins/builtin/skills_plugin.py:104` | Skill 使用指南、命名规则、Hard Constraints |
| **GitPlugin** | `plugins/builtin/git_plugin.py:20` | Git 操作指南 |
| **SearchPlugin** | `plugins/builtin/search_plugin.py:19` | Web Search 指南 |
| **MCPGatewayPlugin** | `plugins/builtin/mcp_gateway_plugin.py:296` | MCP 服务器工具说明 |

### 5.1 PlanPlugin

```python
@hookimpl
def get_system_prompt(self) -> str:
    """Inject MANDATORY planning rules into the agent's system prompt."""
    return """## MANDATORY PLANNING RULES - YOU MUST FOLLOW

### CHECK: Is this a COMPLEX task?
BEFORE taking any action, ask yourself:
1. Does it require 3+ steps or tool calls?
2. Does it involve multiple files or modules?
3. Is the scope unclear or ambiguous?
4. Does it require architecture decisions or unfamiliar code areas?
5. Are there risks (file writes, data migration, breaking changes)?

### RULE 1: IF complex, YOU MUST CALL plan_task FIRST
If you answered YES to ANY question above:
→ STOP immediately
→ Call `plan_task(task="...", num_plans=2)` BEFORE any other action
→ Do NOT start executing tools directly

### RULE 2: NEVER skip planning for multi-step tasks
...
"""
```

### 5.2 SkillsPlugin

```python
@hookimpl
def get_system_prompt(self) -> str:
    lines = [
        "## Claude Code Skills",
        "",
        "Available skill management tools:",
        "- `list_skills`: List all loaded skills and their descriptions",
        "- `get_skill(name)`: Get full skill content (SKILL.md)",
        "- `search_skills(query)`: Search skills by keyword",
        ...
        "## Skill Naming Rules",
        "IMPORTANT: Skill tool names and skill names are different.",
        "- Skill tools are named `skill_<name>`",
        "- Skill names for `get_skill(name)` are SHORT names WITHOUT `skill_` prefix",
        ...
        "## Hard Constraints — Never Violate",
        "- NEVER use `write_file` to create a .docx file",
        "- For .docx creation: use the docx skill's specified workflow",
        ...
        "## Skill Self-Healing — When a Skill Workflow Fails",
        ...
    ]
    return "\n".join(lines)
```

---

## 6. Skill 加载机制

### 6.1 位置
`plugins/builtin/skills_plugin.py`

### 6.2 Skill 搜索路径 (优先级递减)

```
1. ./.py-code-agent/skills/        (项目本地 — 最高)
2. ~/.config/py-code-agent/skills/ (全局配置)
3. ~/.claude/skills/               (用户目录 — 最低)
```

### 6.3 加载流程

```python
SKILL_CACHE: Dict[str, Dict[str, Any]] = {}

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

def _load_skill_file(skill_dir: Path) -> Optional[Dict[str, Any]]:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None

    content = skill_md.read_text(encoding="utf-8")
    name = skill_dir.name
    description = ""
    frontmatter = {}

    # 解析 frontmatter
    fm_match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
    if fm_match:
        for line in fm_match.group(1).split("\n"):
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
```

### 6.4 SkillsPlugin.get_system_prompt() 返回内容

1. **Skill 列表** - 当前加载的所有 skill
2. **Skill Naming Rules** - `skill_<name>` vs `get_skill(name)` 区别
3. **How to Use a Retrieved Skill** - 必须按顺序遵循 workflow
4. **Hard Constraints** - 禁止用 `write_file` 创建 `.docx` 等
5. **Skill Self-Healing** - 失败恢复流程

---

## 7. Subagent 的 Prompt 继承

### 7.1 位置
`plugins/builtin/plan_plugin.py` → `_run_subtask()`

### 7.2 继承机制

Subagent 继承完整的 plugin/skill 生态系统:

```python
async def _run_subtask(self, subtask: SubTask, agent: Any) -> tuple[bool, str]:
    # OPTION A: 获取 master agent 的 plugin prompts
    plugin_prompts = ""
    try:
        pm = getattr(self._agent_ref, "plugin_manager", None)
        if pm is not None:
            raw = pm.get_system_prompt()
            if isinstance(raw, str) and raw:
                plugin_prompts = raw
    except Exception:
        pass

    # 构建 subagent system prompt
    system_prompt_parts = [
        "You are executing a subtask using the ReAct (Reasoning + Acting) pattern. "
        "Think step by step, then act.",
        "",
        f"Subtask title: {subtask.title}",
        f"Subtask description: {subtask.description}",
        "",
        "Follow this format:",
        "Thought: [Your step-by-step reasoning]",
        "Action: [The tool call or final answer]",
    ]

    # OPTION B: 注入 skill workflow context
    if subtask.skill_context:
        system_prompt_parts.extend([
            "",
            "## Required Skill Workflow",
            "IMPORTANT: This subtask requires using a specific skill workflow.",
            subtask.skill_context,
        ])

    # OPTION A: 追加所有 plugin system prompts
    if plugin_prompts:
        system_prompt_parts.extend([
            "",
            "## Plugin & Skill Guidance",
            plugin_prompts,
        ])
```

---

## 8. 完整加载流程图

```
┌──────────────────────────────────────────────────────────────┐
│ 1. Agent 初始化                                              │
│    └─ _setup_plugins() → PluginManager                     │
│         ├─ 加载内置插件 (plugins/builtin/)                   │
│         ├─ 加载本地插件 (.py-code-agent/plugins/)           │
│         ├─ 加载全局插件 (~/.config/py-code-agent/plugins/)   │
│         └─ 注册 entry points (PyPI)                         │
└────────────────────────────┬─────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────┐
│ 2. 每次 LLM 调用前                                           │
│    └─ _prepare_messages()                                    │
│         ├─ 生成 Base Prompt (ReAct 或标准模式)               │
│         └─ 调用 plugin_manager.call_get_system_prompt()       │
│              └─ 遍历插件，聚合所有 get_system_prompt()       │
└────────────────────────────┬─────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────┐
│ 3. 最终 System Message                                        │
│    └─ Base Prompt + "\n\n" + Plugin Prompts                  │
│         └─ 发送给 LLM                                        │
└──────────────────────────────────────────────────────────────┘
```

---

## 10. 动态插件加载机制

### 10.1 设计理念

插件加载采用**LLM 驱动 + 声明式依赖**的混合模式：

| 机制 | 声明位置 | 加载时机 | 实现 |
|------|---------|---------|------|
| **静态依赖** | 插件类 docstring | 启动时 | `_load_dependencies()` |
| **动态依赖** | `get_system_prompt()` 返回值 | 运行时 | `<plugin_depends>` 标签 + `load_plugins` 工具 |

### 10.2 静态依赖：启动时自动加载

**声明位置**: 插件类 docstring

```python
# plugins/builtin/plan_plugin.py:1089-1101
class PlanPlugin:
    """Plugin for complex task planning...

    Dependencies:
        - ContextPlugin (file:context): provides context tool for subtask coordination
    """
```

**解析逻辑**: `manager.py:300-341`

```python
def _load_dependencies(self, plugin_dirs: List[Path]) -> None:
    loaded = set(self._plugin_names)
    
    for name in list(self._plugin_names):
        plugin = self.pm.get_plugin(name)
        docstring = getattr(plugin.__class__, "__doc__", "") or ""
        
        # 正则匹配 Dependencies: 段落
        dep_section = re.search(r"Dependencies:\s*\n((?:\s*-.*\n)+)", docstring, re.MULTILINE)
        if dep_section:
            for line in dep_section.group(1).split("\n"):
                match = re.search(r"\(file:([\w-]+)\)", line)
                if match:
                    deps.append(f"file:{match.group(1)}")
        
        # 自动加载依赖插件
        for dep_name in deps:
            if dep_name not in loaded:
                self._load_plugin_file(py_file)
```

### 10.3 动态依赖：运行时 LLM 决定

#### 10.3.1 `<plugin_depends>` 标签

**位置**: 插件 `get_system_prompt()` 返回值开头

```python
# plugins/builtin/plan_plugin.py:1147-1150
@hookimpl
def get_system_prompt(self) -> str:
    return """<plugin_depends>file:context</plugin_depends>

## CRITICAL: YOUR FIRST ACTION IS FIXED
...
"""
```

**作用**:
- 嵌入在系统提示词中，告诉 LLM 该插件依赖哪些其他插件
- LLM 分析提示词后自行决定是否调用 `load_plugins` 加载

#### 10.3.2 `load_plugins` 工具

**定义位置**: `manager.py:1173-1230`

```python
class LoadPluginsTool(BaseTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="load_plugins",
            description="Load and enable plugins by name...",
            parameters=[
                ToolParameter(
                    name="plugins",
                    type=ToolParameterType.STRING,
                    description="Comma-separated list of plugin names (e.g., 'context,plan')",
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

    async def execute(self, plugins: str = "", reason: str = "", **kwargs) -> ToolResult:
        plugin_list = [p.strip() for p in plugins.split(",") if p.strip()]
        for plugin_name in plugin_list:
            full_name = f"file:{plugin_name}"
            self.plugin_manager.enable_plugin(full_name)
```

**注册方式**: 通过 `PluginPlugin` 类注册 (manager.py:1171-1183)

```python
class PluginPlugin:
    _pm_instance: Optional[PluginManager] = None

    @classmethod
    def set_plugin_manager(cls, pm: PluginManager) -> None:
        cls._pm_instance = pm

    @hooks.hookimpl
    def register_tools(self) -> List[BaseTool]:
        if self._pm_instance:
            return [LoadPluginsTool(self._pm_instance)]
        return []
```

**Agent 初始化时注册** (agent.py:111-116):

```python
PluginPlugin.set_plugin_manager(self.plugin_manager)
plugin_plugin_instance = PluginPlugin()
self.plugin_manager.pm.register(plugin_plugin_instance, name="file:plugin")
self.plugin_manager._plugin_names.append("file:plugin")
self.plugin_manager._health["file:plugin"] = PluginHealth(name="file:plugin", loaded_at=datetime.now())
```

**使用示例**:
```
load_plugins(plugins="context,plan", reason="需要上下文共享和规划功能")
```

#### 10.3.3 `enable_plugin()` 方法

**位置**: `manager.py:345-375`

```python
def enable_plugin(self, name: str) -> bool:
    """Dynamically enable a plugin by name."""
    if name.startswith("file:"):
        canonical = name[5:]
        full_name = name
    else:
        canonical = name
        full_name = f"file:{name}"
    
    # 已加载且启用则跳过
    if full_name in self._plugin_names and self._is_enabled(full_name):
        return True
    
    # 从 builtin 目录动态加载
    if full_name not in self._plugin_names:
        builtin_dir = Path(__file__).parent.parent.parent / "plugins" / "builtin"
        plugin_file = builtin_dir / f"{canonical}_plugin.py"
        if plugin_file.exists():
            self._load_plugin_file(plugin_file)
    
    # 添加到启用列表
    if full_name in self._plugin_names:
        if full_name not in self._plugin_config.enabled:
            self._plugin_config.enabled.append(full_name)
        if full_name in self._plugin_config.disabled:
            self._plugin_config.disabled.remove(full_name)
        return True
    return False
```

### 10.4 完整加载流程

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. Agent 初始化 (agent.py:97-121)                              │
│    ├─ 创建 PluginManager                                        │
│    ├─ load_plugins() 加载所有插件                               │
│    │   ├─ _load_from_entry_points() → PyPI 包                 │
│    │   ├─ _load_from_dir() → 本地目录                          │
│    │   └─ _load_dependencies() → 静态依赖解析                 │
│    ├─ 注册 PluginPlugin (含 load_plugins 工具)                  │
│    ├─ register_tools() → 获取所有插件工具                       │
│    └─ 健康检查与自愈                                            │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. 每次 LLM 调用前 (_prepare_messages)                         │
│    ├─ 构建 Base Prompt (ReAct 或标准模式)                       │
│    └─ call_get_system_prompt() → 聚合插件提示词                │
│         └─ 每个插件 get_system_prompt() 包装为 XML 标记         │
│              <!-- [PLUGIN:plan] -->                            │
│              <plugin_depends>file:context</plugin_depends>     │
│              ## CRITICAL: YOUR FIRST ACTION IS FIXED           │
│              <!-- [/PLUGIN:plan] -->                           │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. LLM 接收系统提示词                                           │
│    └─ 发现 <plugin_depends>file:context 依赖                   │
│         └─ 理解需要 context 插件                               │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. LLM 自主决策                                                 │
│    └─ 调用 load_plugins(plugins="context", reason="...")        │
│         ├─ enable_plugin("file:context")                       │
│         └─ register_tools() → 注册新工具                        │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. 继续执行任务                                                 │
│    └─ context 工具现在可用                                      │
└─────────────────────────────────────────────────────────────────┘
```

### 10.5 核心实现索引

| 功能 | 文件位置 |
|------|---------|
| 插件加载入口 | `manager.py:292-298` (load_plugins) |
| 静态依赖解析 | `manager.py:300-341` (_load_dependencies) |
| 动态加载方法 | `manager.py:345-375` (enable_plugin) |
| 聚合系统提示 | `manager.py:688-727` (call_get_system_prompt) |
| LLM 加载工具 | `manager.py:1173-1230` (LoadPluginsTool) |
| 依赖声明示例 | `plan_plugin.py:1089-1101` (docstring) |
| 依赖标签示例 | `plan_plugin.py:1147-1150` (get_system_prompt) |

---

## 11. 关键文件索引

| 文件 | 作用 |
|------|------|
| `src/py_code_agent/core/agent.py` | Agent 主类，Base Prompt 定义 |
| `src/py_code_agent/plugins/hooks.py` | Hookspec 定义 (`get_system_prompt`) |
| `src/py_code_agent/plugins/manager.py` | Plugin 加载、聚合、动态加载 |
| `plugins/builtin/skills_plugin.py` | Skill 发现与加载 |
| `plugins/builtin/plan_plugin.py` | 任务规划规则，含 `<plugin_depends>` |
| `plugins/builtin/context_plugin.py` | 上下文共享插件 |
| `plugins/builtin/git_plugin.py` | Git 操作指南 |
| `plugins/builtin/search_plugin.py` | 搜索功能指南 |
| `plugins/builtin/mcp_gateway_plugin.py` | MCP 网关指南 |
| `tests/test_plugin_system_prompts.py` | 提示词测试 |

---

## 12. 扩展开发指南

### 12.1 添加新的 Plugin Prompt

1. 在插件类中实现 `get_system_prompt()` 方法
2. 使用 `@hookimpl` 装饰器标记
3. 如有依赖，添加 `<plugin_depends>` 标签

```python
from py_code_agent.plugins.hooks import hookimpl

class MyPlugin:
    @hookimpl
    def get_system_prompt(self) -> str:
        return """<plugin_depends>file:context</plugin_depends>

## My Custom Plugin Guidance

This plugin adds specialized instructions for...
"""
```

### 12.2 添加静态依赖声明

在插件类 docstring 中添加:

```python
class MyPlugin:
    """Description of my plugin.

    Dependencies:
        - ContextPlugin (file:context): provides context for coordination
    """
```

### 12.3 添加新的 Skill

1. 在 `~/.claude/skills/` 下创建目录
2. 添加 `SKILL.md` 文件
3. 可选：添加 frontmatter 定义 name 和 description

```markdown
---
name: my-skill
description: A skill for doing something specific
---

# My Skill

Instructions for using this skill...
```

---

## 13. Channel Prompt 机制

### 13.1 概述

Channel Prompt 是 Channel 层向 LLM 提供的上下文信息，用于指导 LLM 如何与特定通道的用户通信。

### 13.2 位置

`src/py_code_agent/channels/websocket.py` → `WebSocketChannel.get_channel_prompt()`

### 13.3 WebSocket Channel Prompt

```python
def get_channel_prompt(self) -> str:
    return """You are a WebSocket Channel assistant.
Keep users informed during task execution:
- Use send_message to send progress updates to users while working on tasks
- Use send_file to send file content to users when files are generated

Note: Always use the current client's client_id when sending messages or files."""
```

### 13.4 Channel Prompt 注入流程

```
CLI (main.py)
  │
  ▼
run_agent_on_channel(channel, agent, "websocket")
  │
  ▼
channel.receive() ← 获取客户端消息
  │
  ▼
获取 client_id from msg.metadata
  │
  ▼
context_prefix = channel.get_channel_prompt() + " [Current Client: xxx]"
  │
  ▼
agent.run(context_prefix + msg.content)
  │
  ▼
LLM 获得完整的上下文，包含 Channel Prompt
```

### 13.5 Channel Tools 注册

WebSocketChannel 提供两个工具供 LLM 调用：

| 工具 | 参数 | 用途 |
|------|------|------|
| `send_message` | `client_id`, `content` | 发送消息给用户 |
| `send_file` | `client_id`, `file_path` | 发送文件给用户 (Base64) |

注册流程：

```python
# main.py
agent = Agent(config)
for tool in ws_channel.get_channel_tools():
    agent.register_tool(tool)
```

### 13.6 消息类型

Channel 发送的消息根据 `metadata.type` 区分：

| type | 字段 | 说明 |
|------|------|------|
| `message` | `message` | 普通文本消息 |
| `status` | `status` | 状态更新 (processing/thinking/done) |
| `file` | `file` | Base64 编码的文件内容 |

### 13.7 扩展新的 Channel

1. 继承 `BaseChannel` 实现 Channel 类
2. 实现 `get_channel_prompt()` 方法返回提示词
3. 实现 `get_channel_tools()` 方法返回工具列表
4. 在 CLI 中注册 channel 命令并注册工具到 Agent
