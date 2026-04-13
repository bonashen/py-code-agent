# Py Code Agent 对标 pi-coding-agent 核心包深度分析报告

## 执行摘要

本报告对比分析 Py Code Agent 与 pi-mono 项目中的 `@mariozechner/pi-coding-agent` 核心包，识别关键差距并提出优先级改进建议。

**核心发现：**
- pi-coding-agent 拥有 **46+ 事件类型**的完整 Hook 系统，Py Code Agent 仅 **12 个 hook specs**
- pi-coding-agent 提供 **10+ 扩展 API**（工具/命令/快捷键/CLI 标志/UI 组件），Py Code Agent 仅 **3 个**
- pi-coding-agent 实现 **4 种运行模式**（交互/打印/JSON/RPC）+ SDK 嵌入，Py Code Agent 仅 **2 种**
- Py Code Agent 独有优势：**5 层自愈机制**、**MCP/A2A 原生支持**、**Python 生态**

---

## 一、架构对比

### 1.1 核心设计哲学

| 维度 | pi-coding-agent | Py Code Agent |
|------|-----------------|---------------|
| **定位** | 极简终端编码 Harness | Python AI Agent 框架 |
| **默认工具** | 4 个 (read/write/edit/bash) | 动态加载 (计划/Skills/Git/MCP 等) |
| **系统提示词** | ~200 tokens | 动态构建 (插件贡献) |
| **扩展方式** | Extensions/Skills/Prompts/Themes | Plugins/Tools/Skills |
| **不内置功能** | Sub-agents, Plan mode, MCP, Permission popups | 无明确限制 |
| **语言** | TypeScript (Bun/Node) | Python |

### 1.2 项目结构对比

```
pi-coding-agent (TypeScript)
├── src/
│   ├── cli/              # CLI 参数/配置/会话选择
│   ├── core/
│   │   ├── agent-session.ts      # 会话运行时
│   │   ├── event-bus.ts          # 事件总线 (2 个接口)
│   │   ├── extensions/           # 扩展系统核心
│   │   │   ├── types.ts          # 46+ 事件类型定义
│   │   │   ├── loader.ts         # 扩展加载器
│   │   │   └── ExtensionAPI      # 10+ API 方法
│   │   ├── session-manager.ts    # JSONL 树形会话管理
│   │   ├── compaction/           # 上下文压缩
│   │   ├── slash-commands.ts     # 斜杠命令系统
│   │   ├── keybindings.ts        # 键盘快捷键
│   │   ├── tools/                # 内置工具
│   │   └── modes/
│   │       ├── interactive/      # TUI 交互模式
│   │       ├── print-mode.ts     # 打印模式
│   │       └── rpc/              # RPC 模式 (JSONL)
│   └── modes/
│       └── interactive/
│           └── theme/            # 主题系统
└── packages/
    ├── pi-ai/                    # 统一 LLM API
    ├── pi-agent-core/            # Agent 运行时
    ├── pi-tui/                   # 终端 UI 库
    └── pi-web-ui/                # Web 聊天界面

Py Code Agent (Python)
├── src/py_code_agent/
│   ├── cli/                      # CLI 入口
│   ├── core/                     # 核心逻辑
│   ├── plugins/
│   │   ├── hooks.py              # 12 hook specs (pluggy)
│   │   ├── manager.py            # 插件管理器 (5 层自愈)
│   │   └── auto_repair.py        # AI 自动修复
│   ├── tools/                    # 工具系统
│   ├── mcp/                      # MCP 网关
│   └── channels/                 # 通信通道
└── plugins/
    └── builtin/                  # 内置插件
```

---

## 二、Hook/事件系统详细对比

### 2.1 事件数量与类型

| 类别 | pi-coding-agent 事件 | Py Code Agent Hooks | 差距 |
|------|---------------------|---------------------|------|
| **资源发现** | `resources_discover` | ❌ | 🔴 |
| **会话生命周期** | `session_start`, `session_before_switch`, `session_before_fork`, `session_before_tree`, `session_tree`, `session_shutdown` | ❌ | 🔴 |
| **上下文压缩** | `session_before_compact`, `session_compacted` | ❌ | 🔴 |
| **Agent 生命周期** | `before_agent_start`, `agent_start`, `agent_end`, `turn_start`, `turn_end` | `on_agent_start`, `on_agent_end` | 🟡 |
| **消息流式** | `message_start`, `message_update`, `message_end` | ❌ | 🔴 |
| **工具执行流** | `tool_execution_start`, `tool_execution_update`, `tool_execution_end` | `before_tool_execute`, `after_tool_execute` | 🔴 |
| **工具调用** | `bash_tool_call`, `read_tool_call`, `edit_tool_call`, `write_tool_call`, `grep_tool_call`, `find_tool_call`, `ls_tool_call`, `custom_tool_call` | ❌ | 🔴 |
| **工具结果** | `bash_tool_result`, `read_tool_result`, `edit_tool_result`, `write_tool_result`, `grep_tool_result`, `find_tool_result`, `ls_tool_result`, `custom_tool_result` | ❌ | 🔴 |
| **模型选择** | `model_select` | ❌ | 🔴 |
| **用户输入** | `input`, `user_bash` | ❌ | 🔴 |
| **LLM 调用** | `before_provider_request` | `on_llm_call`, `on_llm_response` | 🟢 |
| **插件心跳** | ❌ | `on_plugin_heartbeat` | ✅ Py 独有 |
| **能力发现** | ❌ | `get_capabilities` | ✅ Py 独有 |
| **错误增强** | ❌ | `enhance_tool_error` | ✅ Py 独有 |
| **系统提示** | ❌ | `get_system_prompt` | 🟢 |
| **总计** | **46+ 事件** | **12 hooks** | **3.8x 差距** |

### 2.2 事件系统设计对比

**pi-coding-agent EventBus:**
```typescript
// 简单 EventEmitter 封装
export interface EventBus {
  emit(channel: string, data: unknown): void;
  on(channel: string, handler: (data: unknown) => void): () => void;
}

// 46+ 事件类型联合
export type ExtensionEvent =
  | ResourcesDiscoverEvent
  | SessionEvent
  | ContextEvent
  | BeforeProviderRequestEvent
  | BeforeAgentStartEvent
  | AgentStartEvent
  | AgentEndEvent
  | TurnStartEvent
  | TurnEndEvent
  | MessageStartEvent
  | MessageUpdateEvent
  | MessageEndEvent
  | ToolExecutionStartEvent
  | ToolExecutionUpdateEvent
  | ToolExecutionEndEvent
  | ModelSelectEvent
  | UserBashEvent
  | InputEvent
  | ToolCallEvent
  | ToolResultEvent;
```

**Py Code Agent (pluggy):**
```python
# 使用 pluggy 框架
hookspec = pluggy.HookspecMarker("py_code_agent")

class ToolHooks:
    @hookspec
    def register_tools(self) -> List[BaseTool]: ...
    
    @hookspec
    def before_tool_execute(self, tool_name: str, arguments: Dict): ...
    
    @hookspec
    def after_tool_execute(self, tool_name: str, arguments: Dict, result: Any): ...

class AgentHooks:
    @hookspec
    def on_agent_start(self, input: str): ...
    
    @hookspec
    def on_agent_end(self): ...
    
    @hookspec
    def on_llm_call(self, messages: List, tools: List): ...
```

**关键差异：**
1. pi-coding-agent 事件更细粒度（消息/工具执行的 start/update/end 三段式）
2. pi-coding-agent 有完整的会话树事件（fork/switch/tree）
3. Py Code Agent 使用 pluggy 框架，支持优先级和多结果聚合
4. Py Code Agent 有独特的错误增强和心跳机制

---

## 三、扩展 API 详细对比

### 3.1 API 能力矩阵

| API 能力 | pi-coding-agent ExtensionAPI | Py Code Agent | 差距 |
|----------|------------------------------|---------------|------|
| **注册工具** | `registerTool(tool)` | `register_tools` hook | ✅ |
| **注册命令** | `registerCommand(name, options)` | ❌ | 🔴 |
| **注册快捷键** | `registerShortcut(keys, handler)` | ❌ | 🔴 |
| **注册 CLI 标志** | `registerFlag(name, options)` | ❌ | 🔴 |
| **事件订阅** | `on(event, handler)` - 25+ 事件 | pluggy hooks - 12 个 | 🔴 |
| **UI 选择器** | `ui.select(title, options)` | ❌ | 🔴 |
| **UI 确认框** | `ui.confirm(title, message)` | ❌ | 🔴 |
| **UI 输入框** | `ui.input(title, placeholder)` | ❌ | 🔴 |
| **UI 通知** | `ui.notify(message, type)` | ❌ | 🔴 |
| **UI 状态栏** | `ui.setStatus(key, text)` | ❌ | 🔴 |
| **UI Widget** | `ui.setWidget(key, content, placement)` | ❌ | 🔴 |
| **UI Header/Footer** | `ui.setHeader()`, `ui.setFooter()` | ❌ | 🔴 |
| **UI 自定义组件** | `ui.custom(factory)` | ❌ | 🔴 |
| **UI 编辑器替换** | `ui.setEditorComponent(factory)` | ❌ | 🔴 |
| **主题管理** | `ui.getTheme()`, `ui.setTheme()` | ❌ | 🔴 |
| **会话控制** | `ctx.newSession()`, `ctx.fork()`, `ctx.navigateTree()` | ❌ | 🔴 |
| **上下文压缩** | `ctx.compact(options)` | ❌ | 🔴 |
| **模型调用** | `ctx.model.simpleStream()` | LiteLLM 直接调用 | 🟢 |
| **自定义 Provider** | `registerProvider()` | ❌ | 🔴 |
| **消息渲染器** | `registerMessageRenderer()` | ❌ | 🔴 |
| **API 总数** | **20+** | **3** | **6.7x 差距** |

### 3.2 pi-coding-agent ExtensionAPI 示例

```typescript
export default function(pi: ExtensionAPI) {
  // 1. 注册工具
  pi.registerTool({
    name: "deploy",
    label: "Deploy",
    description: "Deploy to production",
    parameters: Schema.Object({ environment: Schema.String() }),
    execute: async (toolCallId, params, signal, onUpdate, ctx) => {
      // 工具执行逻辑
      return { success: true, content: "Deployed" };
    }
  });

  // 2. 注册命令
  pi.registerCommand("stats", {
    description: "Show project statistics",
    action: async (args, ctx) => {
      await ctx.ui.notify("Calculating...", "info");
      // 命令逻辑
    }
  });

  // 3. 注册快捷键
  pi.registerShortcut(["ctrl+k"], {
    command: "stats",
    description: "Show stats"
  });

  // 4. 订阅事件
  pi.on("tool_call", async (event, ctx) => {
    if (event.tool.name === "bash") {
      // 拦截 bash 工具调用
    }
  });

  // 5. UI 组件
  pi.ui.setWidget("status", ["Building..."], { placement: "belowEditor" });
  pi.ui.setStatus("build", "Building...");
  
  // 6. 会话控制
  pi.on("session_start", async (event, ctx) => {
    await ctx.fork("some-entry-id");
  });
}
```

### 3.3 Py Code Agent 插件示例

```python
from py_code_agent.plugins.hooks import hookimpl
from py_code_agent.tools.base import BaseTool

class MyPlugin:
    @hookimpl
    def register_tools(self) -> List[BaseTool]:
        return [MyCustomTool()]
    
    @hookimpl
    def before_tool_execute(self, tool_name: str, arguments: Dict):
        logger.info(f"Tool {tool_name} executing with {arguments}")
    
    @hookimpl
    def get_system_prompt(self) -> str:
        return "Additional instructions..."
```

---

## 四、会话管理系统对比

### 4.1 存储格式

**pi-coding-agent (JSONL 树形结构):**
```jsonl
{"id": "msg-001", "parentId": null, "type": "user", "content": "Hello", "timestamp": "..."}
{"id": "msg-002", "parentId": "msg-001", "type": "assistant", "content": "Hi!", "timestamp": "..."}
{"id": "msg-003", "parentId": "msg-001", "type": "user", "content": "Branch here", "timestamp": "..."}
{"id": "msg-004", "parentId": "msg-003", "type": "assistant", "content": "OK", "timestamp": "..."}
```

**Py Code Agent:**
- 当前实现：未找到明确的会话树存储
- 需要实现 JSONL + parentId 树形结构

### 4.2 会话命令对比

| 命令 | pi-coding-agent | Py Code Agent | 差距 |
|------|-----------------|---------------|------|
| `/tree` | ✅ 可视化树导航 | ❌ | 🔴 |
| `/fork` | ✅ 创建分支会话 | ❌ | 🔴 |
| `/switch` | ✅ 切换节点 | ❌ | 🔴 |
| `/compact` | ✅ 手动压缩 | ❌ | 🔴 |
| `/export` | ✅ HTML 导出 | ❌ | 🔴 |
| `/share` | ✅ GitHub Gist 分享 | ❌ | 🔴 |
| `/resume` | ✅ 选择历史会话 | ❌ | 🟡 |
| CLI `-c` | ✅ 继续最近会话 | ❌ | 🟡 |
| CLI `-r` | ✅ 浏览历史会话 | ❌ | 🟡 |
| CLI `--fork` | ✅ CLI fork | ❌ | 🔴 |

### 4.3 上下文压缩

**pi-coding-agent:**
- 自动触发：接近上下文限制时主动压缩
- 手动触发：`/compact [custom instructions]`
- 可定制：通过扩展自定义压缩策略
- 事件：`session_before_compact`, `session_compacted`

**Py Code Agent:**
- 当前实现：未找到压缩机制
- 需要实现自动 + 手动压缩

---

## 五、运行模式对比

| 模式 | pi-coding-agent | Py Code Agent | 说明 |
|------|-----------------|---------------|------|
| **交互模式** | ✅ TUI (基于 pi-tui) | ✅ CLI | pi 有完整 TUI |
| **打印模式** | ✅ `-p` flag | ❌ | Py 需实现 |
| **JSON 模式** | ✅ `--mode json` | ❌ | Py 需实现 |
| **RPC 模式** | ✅ `--mode rpc` (JSONL over stdin/stdout) | ❌ | Py 需实现 |
| **SDK 嵌入** | ✅ `createAgentSession()` | ❌ | Py 需实现 |
| **Web UI** | ✅ pi-web-ui 包 | ❌ | Py 可选 |

**RPC 模式示例 (pi-coding-agent):**
```bash
# JSONL over stdin/stdout
echo '{"type": "message", "content": "Hello"}' | pi --mode rpc
# 输出：{"type": "response", "content": "Hi there!"}
```

**SDK 嵌入示例 (pi-coding-agent):**
```typescript
import { createAgentSession } from "@mariozechner/pi-coding-agent";

const session = await createAgentSession({
  cwd: "/path/to/project",
  model: "anthropic:claude-sonnet-4-20250514",
});

await session.send("Refactor this code");
session.on("message", (msg) => console.log(msg));
```

---

## 六、Py Code Agent 独特优势

### 6.1 5 层自愈机制

Py Code Agent 独有的插件健康管理系统：

```python
@dataclass
class PluginHealth:
    name: str
    loaded_at: Optional[datetime]
    success_count: int
    failure_count: int
    last_error: Optional[str]
    disabled: bool
    disabled_reason: Optional[str]
    
    @property
    def is_healthy(self) -> bool:
        return not self.disabled and self.failure_count < 3

# 5 层防护：
# 1. try/except 包裹所有插件代码
# 2. 每 hook 调用超时保护 (默认 5 秒)
# 3. 致命异常立即禁用插件 (SystemExit, MemoryError)
# 4. 不可恢复错误禁用 (TypeError, AttributeError)
# 5. AI 自动修复 (AiAutoRepair)
```

**pi-coding-agent:** 无类似机制，插件崩溃可能导致整个进程退出。

### 6.2 MCP/A2A 原生支持

**Py Code Agent:**
- `py_code_agent_mcp_gateway`: MCP 服务器/客户端网关
- `py_code_agent_a2a_gateway`: A2A 协议支持
- 作为核心功能内置

**pi-coding-agent:**
- 明确拒绝内置 MCP
- 需通过 Extension 实现
- README: "Pi ships with powerful defaults but skips features like sub agents and plan mode."

### 6.3 Python 生态系统

| 优势 | Py Code Agent | pi-coding-agent |
|------|---------------|-----------------|
| **LLM 提供商** | LiteLLM (100+ 提供商) | 自研 pi-ai (20+ 提供商) |
| **数据科学** | pandas/numpy/scikit-learn | ❌ |
| **AI 框架** | LangChain/LlamaIndex | ❌ |
| **企业集成** | Django/FastAPI 生态 | Node.js 生态 |

---

## 七、优先级改进建议

### 🔴 高优先级（基础架构，1-2 月）

#### 1. 扩展 Hook 事件系统至 30+ 事件

**目标：** 从 12 hooks → 30+ hooks

**新增事件：**
```python
# 会话事件 (6 个)
session_start(reason: str, previous_session: Optional[str])
session_before_switch(target_id: str)
session_before_fork(entry_id: str)
session_before_tree()
session_tree(entries: List[SessionEntry])
session_shutdown()

# 消息流式事件 (3 个)
message_start(message_id: str, role: str)
message_update(message_id: str, content_delta: str)
message_end(message_id: str, full_content: str)

# 工具执行流事件 (3 个)
tool_execution_start(tool_call_id: str, tool_name: str, args: Dict)
tool_execution_update(tool_call_id: str, details: Any)
tool_execution_end(tool_call_id: str, result: ToolResult)

# 工具调用/结果事件 (8 个)
bash_tool_call(arguments: BashToolInput)
read_tool_call(arguments: ReadToolInput)
edit_tool_call(arguments: EditToolInput)
write_tool_call(arguments: WriteToolInput)
# ... 对应 result 事件

# 上下文压缩事件 (2 个)
session_before_compact(instructions: str)
session_compacted(summary: str, removed_messages: int)

# 模型选择事件 (1 个)
model_select(selected_model: str, previous_model: str)

# 用户输入事件 (2 个)
input(text: str, attachments: List)
user_bash(command: str, send_to_llm: bool)
```

**实施步骤：**
1. 修改 `hooks.py` 添加新 hook specs
2. 在 `manager.py` 中实现事件发射点
3. 更新内置插件适配新 hooks
4. 编写文档和示例

#### 2. 实现会话树/分支功能

**目标：** 实现 JSONL 树形存储 + `/tree` `/fork` `/switch` 命令

**数据结构：**
```python
@dataclass
class SessionEntry:
    id: str  # UUID
    parent_id: Optional[str]
    type: Literal["user", "assistant", "tool_call", "tool_result"]
    content: str
    timestamp: datetime
    metadata: Dict  # token_count, cost, etc.
```

**存储格式 (~/.pi/sessions/<project>/<session>.jsonl):**
```jsonl
{"id": "msg-001", "parent_id": null, "type": "user", "content": "Hello", ...}
{"id": "msg-002", "parent_id": "msg-001", "type": "assistant", ...}
{"id": "msg-003", "parent_id": "msg-001", "type": "user", "content": "Branch", ...}
```

**命令实现：**
```python
# /tree - 可视化导航
@hookimpl
def register_commands(self) -> List[Command]:
    return [
        Command(
            name="tree",
            description="Navigate session tree",
            handler=self.handle_tree
        ),
        Command(
            name="fork",
            description="Create branch from current point",
            handler=self.handle_fork
        ),
        Command(
            name="switch",
            description="Switch to different node",
            handler=self.handle_switch
        )
    ]
```

#### 3. 增强扩展 API

**目标：** 从 3 APIs → 10+ APIs

**新增 API：**
```python
# 在 PluginManager 或新建 ExtensionContext 类中

class ExtensionContext:
    # 1. 注册命令
    def register_command(self, name: str, handler: Callable, description: str): ...
    
    # 2. 注册快捷键
    def register_shortcut(self, keys: str, handler: Callable, description: str): ...
    
    # 3. 注册 CLI 标志
    def register_cli_flag(self, name: str, help_text: str, default: Any): ...
    
    # 4. UI 方法 (需要 TUI 支持)
    class UI:
        def select(self, title: str, options: List[str]) -> Optional[str]: ...
        def confirm(self, title: str, message: str) -> bool: ...
        def input(self, title: str, placeholder: str = "") -> Optional[str]: ...
        def notify(self, message: str, level: str = "info"): ...
        def set_status(self, key: str, text: str): ...
        def set_widget(self, key: str, content: List[str], placement: str = "below"): ...
    
    # 5. 会话控制
    async def new_session(self, parent_id: Optional[str] = None): ...
    async def fork_session(self, entry_id: str): ...
    async def switch_session(self, entry_id: str): ...
    
    # 6. 上下文压缩
    async def compact(self, instructions: Optional[str] = None): ...
```

### 🟡 中优先级（用户体验，2-3 月）

#### 4. 实时成本追踪
- 每 token 计费显示
- 按会话/天/月统计
- 预算告警

#### 5. 键盘快捷键系统
- 可配置 keybindings.json
- 默认快捷键预设
- 冲突检测

#### 6. 主题/样式系统
- 内置 dark/light 主题
- 热重载主题文件
- 自定义主题 API

#### 7. RPC 模式
- JSONL over stdin/stdout
- 进程间集成
- 与现有 CLI 兼容

### 🟢 低优先级（差异化，3-4 月）

#### 8. SDK 示例库
- Python 嵌入示例
- Web 框架集成 (FastAPI/Django)
- Jupyter Notebook 支持

#### 9. HTML 导出
- 会话导出为 HTML
- GitHub Gist 分享
- PDF 导出

#### 10. 保持 MCP/A2A
- 与 pi-coding-agent 的差异化优势
- 企业级集成场景
- 多 Agent 协作

---

## 八、实施路线图

### Phase 1 (第 1-2 月): 基础架构

| 周次 | 任务 | 交付物 |
|------|------|--------|
| W1-2 | 扩展 hooks.py 至 30+ 事件 | hooks.py v2 |
| W3-4 | 实现会话树存储格式 | session_manager.py |
| W5-6 | 增强 plugin manager 支持事件订阅 | manager.py v2 |
| W7-8 | 单元测试 + 文档 | 测试覆盖率 >80% |

### Phase 2 (第 3-4 月): 核心功能

| 周次 | 任务 | 交付物 |
|------|------|--------|
| W9-10 | 实现 /tree /fork /switch 命令 | commands.py |
| W11-12 | 添加 register_command/shortcut API | extension_api.py |
| W13-14 | 实现消息流式传输 hook | streaming.py |
| W15-16 | 内置插件适配新 API | 所有插件更新 |

### Phase 3 (第 5-6 月): 用户体验

| 周次 | 任务 | 交付物 |
|------|------|--------|
| W17-18 | 实时成本追踪 | cost_tracker.py |
| W19-20 | 主题系统 | themes/ |
| W21-22 | RPC 模式 | rpc_mode.py |
| W23-24 | SDK 示例库 | examples/sdk/ |

---

## 九、关键指标目标

| 指标 | 当前 | 目标 | 提升 |
|------|------|------|------|
| Hook 事件数量 | 12 | 30+ | 2.5x |
| 扩展 API 数量 | 3 | 10+ | 3.3x |
| 运行模式 | 2 | 4 | 2x |
| 会话管理 | 基础 | 树形分支 | 质的飞跃 |
| 测试覆盖率 | ? | >80% | - |
| 文档完整度 | ? | 100% | - |

---

## 十、结论与建议

### 10.1 核心结论

1. **Hook 系统是扩展能力的基石**：pi-coding-agent 的 46+ 事件使其能够支持复杂的扩展场景（子 Agent、计划模式、自定义 UI 等）。Py Code Agent 必须优先补齐这一短板。

2. **会话树是高级功能的基础**：分支、压缩、导出等功能都依赖于树形会话存储。这是 pi-coding-agent 的核心创新之一。

3. **保持差异化优势**：5 层自愈、MCP/A2A、Python 生态是 Py Code Agent 的独特卖点，不应为了对标而放弃。

### 10.2 战略定位建议

**Py Code Agent 应定位为：**
> "极简核心 + 强大扩展 + 企业级集成"

- **极简核心**：学习 pi-coding-agent 的克制，默认只提供必要工具
- **强大扩展**：通过 30+ hooks 和 10+ APIs 实现无限扩展可能
- **企业级集成**：保持 MCP/A2A、自愈机制、Python 生态优势

### 10.3 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 过度工程化 | 高 | 分阶段实施，先 MVP 再迭代 |
| 破坏现有插件 | 中 | 保持向后兼容，提供迁移指南 |
| 性能下降 | 中 | 基准测试，优化热点路径 |
| 文档滞后 | 高 | 文档与代码同步开发 |

---

## 附录 A：pi-coding-agent 完整事件列表

```typescript
// 资源事件 (1)
ResourcesDiscoverEvent

// 会话事件 (6)
SessionStartEvent
SessionBeforeSwitchEvent
SessionBeforeForkEvent
SessionBeforeCompactEvent
SessionCompactEvent
SessionShutdownEvent
SessionBeforeTreeEvent
SessionTreeEvent

// Agent 事件 (5)
ContextEvent
BeforeProviderRequestEvent
BeforeAgentStartEvent
AgentStartEvent
AgentEndEvent
TurnStartEvent
TurnEndEvent

// 消息事件 (3)
MessageStartEvent
MessageUpdateEvent
MessageEndEvent

// 工具执行事件 (3)
ToolExecutionStartEvent
ToolExecutionUpdateEvent
ToolExecutionEndEvent

// 模型事件 (1)
ModelSelectEvent

// 用户输入事件 (2)
UserBashEvent
InputEvent

// 工具调用事件 (8)
BashToolCallEvent
ReadToolCallEvent
EditToolCallEvent
WriteToolCallEvent
GrepToolCallEvent
FindToolCallEvent
LsToolCallEvent
CustomToolCallEvent

// 工具结果事件 (8)
BashToolResultEvent
ReadToolResultEvent
EditToolResultEvent
WriteToolResultEvent
GrepToolResultEvent
FindToolResultEvent
LsToolResultEvent
CustomToolResultEvent

// 总计：46+ 事件类型
```

## 附录 B：参考资源

- pi-mono GitHub: https://github.com/badlogic/pi-mono
- pi-coding-agent README: /workspace/pi-mono/packages/coding-agent/README.md
- pi-coding-agent 事件定义: /workspace/pi-mono/packages/coding-agent/src/core/extensions/types.ts
- Py Code Agent hooks: /workspace/src/py_code_agent/plugins/hooks.py
- Py Code Agent manager: /workspace/src/py_code_agent/plugins/manager.py

---

*报告生成时间：2026 年 4 月 13 日*
*分析基于 pi-mono commit 和 Py Code Agent 当前代码*
