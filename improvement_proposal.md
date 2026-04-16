# Py Code Agent 项目改善建议报告

## 对标 Pi Coding Agent 的差距分析与改进建议

基于对 Pi Coding Agent（通过 pi-vs-claude-code 项目）的深入调研，本报告详细分析了 Py Code Agent 当前的优势与不足，并提供具体的改进建议。

---

## 一、核心架构对比

### 1.1 设计哲学差异

| 维度 | Pi Coding Agent | Py Code Agent (当前) | 建议 |
|------|-----------------|---------------------|------|
| **系统提示词大小** | ~200 tokens（极简） | 未明确，但插件系统可能增加开销 | **优化目标：控制在 500 tokens 以内** |
| **默认工具数量** | 4 个核心工具 (read, write, edit, bash) | 3 个核心工具 + 插件扩展 | ✅ 已符合极简理念 |
| **扩展语言** | TypeScript（零构建） | Python | ✅ 已符合生态 |
| **安全模型** | YOLO 模式（默认无限制） | 路径白名单/黑名单 | ⚠️ 考虑添加"YOLO 模式"选项 |

### 1.2 关键差距

```
┌─────────────────────────────────────────────────────────────┐
│                    Py Code Agent 待改进领域                   │
├─────────────────────────────────────────────────────────────┤
│  🔴 高优先级                                                  │
│  • UI/终端定制能力几乎为零                                   │
│  • Hook 系统不够细粒度（缺少 streaming 级别事件）              │
│  • 缺少多 Agent 编排原生支持                                  │
│  • 没有会话树/分支功能                                       │
│  │                                                          │
│  🟡 中优先级                                                  │
│  • 成本追踪不实时                                            │
│  • 缺少键盘快捷键系统                                        │
│  • 主题/样式定制有限                                         │
│  • 没有 RPC 模式                                              │
│  │                                                          │
│  🟢 低优先级（可选）                                          │
│  • 缺少官方 SDK 示例库                                        │
│  • 没有 HTML 导出功能                                         │
│  • 跨工具技能标准兼容性                                      │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、具体改进建议

### 2.1 【高优先级】增强 Hook 事件系统

#### 现状分析
当前 Py Code Agent 的 Hook 系统包含：
- `on_agent_start/end`
- `on_llm_call/response`
- `before/after_tool_execute`
- `enhance_tool_error`

**缺失的关键事件**（Pi 有 25+ 事件）：
- ❌ `message_streaming`（token-by-token 流式访问）
- ❌ `tool_execution_start/update/end`（工具执行进度流）
- ❌ `session_before_compact/compacted`（上下文压缩控制）
- ❌ `session_fork/switch/tree`（会话树操作）
- ❌ `model_select`（模型切换事件）
- ❌ `context`（直接访问消息上下文）

#### 改进方案

**步骤 1：扩展 events.py**

```python
# src/py_code_agent/core/events.py

class EventType(Enum):
    # 现有事件
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    AGENT_START = "agent_start"
    AGENT_END = "agent_end"
    LLM_CALL = "llm_call"
    LLM_RESPONSE = "llm_response"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    
    # === 新增事件 ===
    # 消息流式传输
    MESSAGE_START = "message_start"
    MESSAGE_UPDATE = "message_update"  # 每个 token
    MESSAGE_END = "message_end"
    
    # 工具执行流
    TOOL_EXECUTION_START = "tool_execution_start"
    TOOL_EXECUTION_UPDATE = "tool_execution_update"  # 流式输出
    TOOL_EXECUTION_END = "tool_execution_end"
    
    # 会话管理
    SESSION_BEFORE_COMPACT = "session_before_compact"
    SESSION_COMPACTED = "session_compacted"
    SESSION_FORK = "session_fork"
    SESSION_SWITCH = "session_switch"
    SESSION_TREE = "session_tree"
    
    # 模型与上下文
    MODEL_SELECT = "model_select"
    CONTEXT_ACCESS = "context_access"
    
    # Agent 轮次
    TURN_START = "turn_start"
    TURN_END = "turn_end"
```

**步骤 2：在 Agent 中触发新事件**

```python
# src/py_code_agent/core/agent.py

async def run(self, input: str) -> AsyncIterator[Event]:
    # ... 现有代码 ...
    
    while turn_count < max_turns:
        # 新增：TURN_START 事件
        await self.plugin_manager.emit_event(
            EventType.TURN_START, 
            {"turn": turn_count}
        )
        
        # 流式 LLM 响应时触发 MESSAGE_* 事件
        assistant_content = ""
        async for event in self.llm.stream(messages, tools):
            if event.type == CONTENT:
                assistant_content += event.data
                # 新增：MESSAGE_UPDATE 事件（每个 token）
                await self.plugin_manager.emit_event(
                    EventType.MESSAGE_UPDATE,
                    {"token": event.data, "accumulated": assistant_content}
                )
            elif event.type == TOOL_CALL:
                assistant_tool_calls.append(event.data)
        
        # 新增：MESSAGE_END 事件
        await self.plugin_manager.emit_event(
            EventType.MESSAGE_END,
            {"content": assistant_content}
        )
        
        # 执行工具时触发 TOOL_EXECUTION_* 事件
        for tc in assistant_tool_calls:
            await self.plugin_manager.emit_event(
                EventType.TOOL_EXECUTION_START,
                {"tool": tc["function"]["name"]}
            )
            
            result = await self._execute_tool(tc)
            
            # 新增：TOOL_EXECUTION_END 事件
            await self.plugin_manager.emit_event(
                EventType.TOOL_EXECUTION_END,
                {"tool": tc["function"]["name"], "result": result}
            )
        
        # 新增：TURN_END 事件
        await self.plugin_manager.emit_event(
            EventType.TURN_END,
            {"turn": turn_count}
        )
```

**步骤 3：更新 hooks.py**

```python
# src/py_code_agent/plugins/hooks.py

class ExtendedHooks:
    """新增 Hook 接口"""
    
    @hookspec
    def on_message_update(self, token: str, accumulated: str) -> None:
        """每个 token 流式传输时触发"""
        
    @hookspec
    def on_tool_execution_start(self, tool_name: str, arguments: Dict) -> None:
        """工具开始执行"""
        
    @hookspec
    def on_tool_execution_update(self, tool_name: str, output: str) -> None:
        """工具执行中的流式输出（如 bash 命令的 stdout）"""
        
    @hookspec
    def on_tool_execution_end(self, tool_name: str, result: ToolResult) -> None:
        """工具执行完成"""
        
    @hookspec
    def on_session_before_compact(self, messages: List[Dict]) -> Optional[List[Dict]]:
        """上下文压缩前，可返回自定义压缩结果"""
        
    @hookspec
    def on_session_compacted(self, compacted_messages: List[Dict]) -> None:
        """上下文压缩后"""
        
    @hookspec
    def on_model_select(self, old_model: str, new_model: str, source: str) -> None:
        """模型切换时（source: user/auto/fallback）"""
        
    @hookspec
    def on_context_access(self, messages: List[Dict]) -> Optional[List[Dict]]:
        """访问上下文时，可过滤/修剪消息"""
```

**预期收益**：
- ✅ 支持实时 UI 更新（类似 Pi 的 footer/widget）
- ✅ 允许插件拦截和修改任意事件
- ✅ 为高级扩展（如子 Agent、安全审计）提供基础

---

### 2.2 【高优先级】实现会话树/分支功能

#### 现状分析
Pi 的会话是 JSONL tree 结构，支持：
- `/fork` - 创建分支
- `/tree` - 查看会话树
- `/switch` - 切换到历史节点

Py Code Agent 当前是线性会话。

#### 改进方案

**步骤 1：扩展 Session 类**

```python
# src/py_code_agent/core/session.py

@dataclass
class SessionNode:
    """会话树节点"""
    id: str
    parent_id: Optional[str]
    message: Dict
    children: List[str] = field(default_factory=list)
    label: Optional[str] = None  # 用户标记
    metadata: Dict = field(default_factory=dict)

class Session:
    def __init__(self):
        self.nodes: Dict[str, SessionNode] = {}
        self.current_node_id: Optional[str] = None
        self.root_id: Optional[str] = None
    
    def add_message(self, role: str, content: str) -> str:
        """添加消息并返回节点 ID"""
        node_id = str(uuid.uuid4())
        node = SessionNode(
            id=node_id,
            parent_id=self.current_node_id,
            message={"role": role, "content": content}
        )
        
        if self.current_node_id and self.current_node_id in self.nodes:
            self.nodes[self.current_node_id].children.append(node_id)
        
        self.nodes[node_id] = node
        
        if not self.root_id:
            self.root_id = node_id
            
        self.current_node_id = node_id
        return node_id
    
    def fork(self, node_id: str) -> str:
        """从指定节点创建分支"""
        if node_id not in self.nodes:
            raise ValueError(f"Node {node_id} not found")
        
        self.current_node_id = node_id
        return self.add_message("system", f"[Forked from {node_id}]")
    
    def switch(self, node_id: str) -> None:
        """切换到历史节点"""
        if node_id not in self.nodes:
            raise ValueError(f"Node {node_id} not found")
        self.current_node_id = node_id
    
    def get_tree(self) -> Dict:
        """获取会话树结构"""
        def build_tree(node_id: str) -> Dict:
            node = self.nodes[node_id]
            return {
                "id": node.id,
                "label": node.label,
                "message": node.message,
                "children": [build_tree(cid) for cid in node.children]
            }
        
        return build_tree(self.root_id) if self.root_id else {}
    
    def get_current_context(self) -> List[Dict]:
        """获取当前分支的完整上下文"""
        if not self.current_node_id:
            return []
        
        path = []
        current = self.current_node_id
        while current:
            node = self.nodes[current]
            path.append(node.message)
            current = node.parent_id
        
        return list(reversed(path))
```

**步骤 2：添加 CLI 命令**

```python
# src/py_code_agent/cli/main.py

@app.command()
def fork(session_id: str = None, label: str = None):
    """从当前或指定会话创建分支"""
    # 实现...

@app.command()
def tree(session_id: str = None):
    """显示会话树"""
    # 实现...

@app.command()
def switch(node_id: str):
    """切换到历史节点"""
    # 实现...
```

**预期收益**：
- ✅ 支持实验性尝试（失败后可回退）
- ✅ 多路径探索（同时尝试多种解决方案）
- ✅ 更好的会话管理

---

### 2.3 【高优先级】添加多 Agent 编排支持

#### 现状分析
Pi 通过扩展支持：
- `/sub <task>` - 后台子 Agent
- Agent Teams - 专家 Agent 团队
- Agent Chains - 顺序管道

Py Code Agent 仅有 A2A Gateway（Agent 间通信），缺少编排层。

#### 改进方案

**步骤 1：创建子 Agent 工具**

```python
# src/py_code_agent/tools/subagent.py

class SubAgentTool(BaseTool):
    """spawn 子 Agent 执行任务"""
    
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="spawn_subagent",
            description="Spawn a background sub-agent to handle isolated tasks",
            parameters=[
                ToolParameter(
                    name="task",
                    type=ToolParameterType.STRING,
                    description="The task to delegate",
                    required=True
                ),
                ToolParameter(
                    name="model",
                    type=ToolParameterType.STRING,
                    description="Model to use (default: same as parent)",
                    required=False
                ),
                ToolParameter(
                    name="mode",
                    type=ToolParameterType.STRING,
                    enum=["single", "parallel", "chain"],
                    description="Execution mode",
                    default="single"
                )
            ]
        )
    
    async def execute(self, task: str, model: str = None, mode: str = "single") -> ToolResult:
        # 创建新的 Agent 实例
        sub_config = self.config.copy()
        if model:
            sub_config.llm.model = model
        
        sub_agent = Agent(sub_config)
        
        # 异步执行
        if mode == "single":
            result = await sub_agent.run(task)
            return ToolResult.ok(data={"status": "completed", "result": result})
        elif mode == "parallel":
            # 并行执行多个子任务
            pass
        elif mode == "chain":
            # 链式执行（输出作为下一个的输入）
            pass
```

**步骤 2：添加 Agent 定义文件**

```yaml
# .py-code-agent/agents/teams.yaml
frontend:
  - planner
  - builder
  - reviewer

backend:
  - architect
  - developer
  - tester
```

```markdown
# .py-code-agent/agents/builder.md
---
name: builder
description: Builds code based on plans
---
You are an expert software builder. Your role is to:
1. Read the plan carefully
2. Implement the code following best practices
3. Write tests for your implementation
4. Verify all tests pass before marking complete
```

**步骤 3：创建编排插件**

```python
# external-plugins/py-code-agent-orchestrator/py_code_agent_orchestrator/plugin.py

class OrchestratorPlugin:
    @hookimpl
    def register_tools(self) -> List[BaseTool]:
        return [
            DispatchAgentTool(),  # /dispatch <agent> <task>
            RunChainTool(),       # /chain <workflow>
            ListAgentsTool()      # /agents
        ]
```

**预期收益**：
- ✅ 专业化分工（不同 Agent 擅长不同任务）
- ✅ 并行执行加速
- ✅ 复杂任务分解

---

### 2.4 【中优先级】实时成本追踪与显示

#### 现状分析
Pi 在 footer 实时显示：
- Token 使用量（in/out/cache）
- 实时成本（$）
- 每工具调用统计

Py Code Agent 缺少实时显示。

#### 改进方案

**步骤 1：扩展 LiteLLM Provider**

```python
# src/py_code_agent/llm/litellm_provider.py

class LiteLLMProvider:
    def __init__(self, config):
        self.session_stats = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cache_read_tokens": 0,
            "total_cost": 0.0,
            "tool_calls": 0
        }
    
    async def stream(self, messages, tools):
        response = await litellm.astream_completion(
            model=self.config.llm.model,
            messages=messages,
            tools=tools,
            stream=True
        )
        
        async for chunk in response:
            yield chunk
            
            # 累积统计
            if hasattr(chunk, 'usage'):
                self.session_stats["prompt_tokens"] += chunk.usage.prompt_tokens
                self.session_stats["completion_tokens"] += chunk.usage.completion_tokens
                
            # 计算成本
            self.session_stats["total_cost"] = self._calculate_cost(
                self.session_stats["prompt_tokens"],
                self.session_stats["completion_tokens"]
            )
    
    def get_stats(self) -> Dict:
        return self.session_stats.copy()
```

**步骤 2：添加状态查询工具**

```python
# src/py_code_agent/tools/stats.py

class SessionStatsTool(BaseTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="session_stats",
            description="Get current session statistics (tokens, cost, tool calls)",
            parameters=[]
        )
    
    async def execute(self) -> ToolResult:
        stats = self.agent.llm.get_stats()
        return ToolResult.ok(data={
            "tokens": {
                "input": stats["prompt_tokens"],
                "output": stats["completion_tokens"],
                "total": stats["prompt_tokens"] + stats["completion_tokens"]
            },
            "cost_usd": round(stats["total_cost"], 6),
            "tool_calls": stats["tool_calls"]
        })
```

**步骤 3：CLI 输出优化**

```python
# src/py_code_agent/cli/chat.py

def print_status(agent):
    stats = agent.llm.get_stats()
    print(f"\r[Tokens: {stats['prompt_tokens']}/{stats['completion_tokens']} | "
          f"Cost: ${stats['total_cost']:.6f} | "
          f"Tools: {stats['tool_calls']}] ", end="")
```

**预期收益**：
- ✅ 成本透明化
- ✅ 帮助用户选择合适模型
- ✅ 识别 token 浪费

---

### 2.5 【中优先级】键盘快捷键系统

#### 现状分析
Pi 支持：
- `Ctrl+P` - 循环切换模型
- `Ctrl+L` - 模糊搜索模型
- `Shift+Tab` - 调整 thinking level
- `Enter` - 中断（steer）
- `Alt+Enter` - 排队消息

Py Code Agent 只有基本 CLI 输入。

#### 改进方案

**步骤 1：使用 prompt_toolkit 增强 CLI**

```python
# src/py_code_agent/cli/chat.py

from prompt_toolkit import Application
from prompt_toolkit.key_binding import KeyBindings

kb = KeyBindings()

@kb.add('c-p')
def _(event):
    """Cycle models"""
    agent.cycle_model()
    print(f"\n[Switched to {agent.config.llm.model}]")

@kb.add('c-l')
def _(event):
    """Fuzzy search models"""
    models = agent.list_models()
    selected = fuzzy_select(models)
    agent.set_model(selected)

@kb.add('s-tab')
def _(event):
    """Adjust thinking level"""
    levels = ["off", "minimal", "low", "medium", "high"]
    current = agent.config.llm.thinking_level
    next_level = levels[(levels.index(current) + 1) % len(levels)]
    agent.set_thinking_level(next_level)

@kb.add('enter')
def _(event):
    """Interrupt current generation (steer)"""
    agent.interrupt()

@kb.add('escape', 'enter')
def _(event):
    """Queue message after completion"""
    agent.queue_message(event.current_buffer.text)

app = Application(key_bindings=kb, ...)
```

**预期收益**：
- ✅ 提升交互效率
- ✅ 无需打断 Agent 即可调整设置
- ✅ 专业用户体验

---

### 2.6 【中优先级】主题与样式系统

#### 现状分析
Pi 有 51 个颜色 token，支持：
- 内置 dark/light 主题
- 社区主题包
- 热重载

Py Code Agent 使用 Rich 库，但无主题系统。

#### 改进方案

**步骤 1：定义主题配置**

```yaml
# ~/.config/py-code-agent/themes/dark.yaml
theme:
  name: "dark"
  colors:
    primary: "#00ff00"
    secondary: "#0088ff"
    success: "#00ff88"
    warning: "#ffaa00"
    error: "#ff4444"
    muted: "#666666"
    accent: "#ff00ff"
```

**步骤 2：创建主题管理器**

```python
# src/py_code_agent/utils/theme.py

class ThemeManager:
    THEMES = {
        "dark": {...},
        "light": {...},
        "monokai": {...}
    }
    
    def __init__(self, theme_name="dark"):
        self.theme = self.load_theme(theme_name)
    
    def get_color(self, token: str) -> str:
        return self.theme["colors"].get(token, "#ffffff")
    
    def apply(self, text: str, token: str) -> str:
        color = self.get_color(token)
        return f"[{color}]{text}[/]"
```

**步骤 3：集成到输出**

```python
# src/py_code_agent/cli/output.py

def render_response(content, theme):
    console.print(theme.apply("🤖 Agent:", "primary"), end=" ")
    console.print(content)

def render_tool_call(tool_name, args, theme):
    console.print(theme.apply(f"🔧 {tool_name}", "accent"))
```

**预期收益**：
- ✅ 个性化体验
- ✅ 品牌定制可能
- ✅ 社区主题生态

---

### 2.7 【低优先级】RPC 模式支持

#### 现状分析
Pi 支持 `--mode rpc`：
- 双向 JSON 协议
- 26+ 命令
- 任意语言客户端

Py Code Agent 仅有 WebSocket。

#### 改进方案

```python
# src/py_code_agent/channels/rpc.py

class RPCChannel(BaseChannel):
    """JSON-RPC 2.0 over stdio/WebSocket"""
    
    COMMANDS = {
        "send_message": self.send_message,
        "get_status": self.get_status,
        "interrupt": self.interrupt,
        "set_model": self.set_model,
        "list_models": self.list_models,
        "export_session": self.export_session,
        # ... 20+ more
    }
    
    async def handle_request(self, request: Dict) -> Dict:
        method = request.get("method")
        params = request.get("params", {})
        
        if method not in self.COMMANDS:
            return {"error": {"code": -32601, "message": "Method not found"}}
        
        try:
            result = await self.COMMANDS[method](**params)
            return {"result": result}
        except Exception as e:
            return {"error": {"code": -32000, "message": str(e)}}
```

**预期收益**：
- ✅ 支持 IDE 插件
- ✅ 支持 Web UI
- ✅ 跨语言集成

---

### 2.8 【低优先级】HTML 导出功能

```python
# src/py_code_agent/core/session.py

def export_to_html(self, output_path: str) -> None:
    template = """
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            .user { background: #e3f2fd; padding: 10px; margin: 5px; }
            .agent { background: #f1f8e9; padding: 10px; margin: 5px; }
            .tool { background: #fff3e0; padding: 5px; margin: 5px; font-family: monospace; }
        </style>
    </head>
    <body>
        {% for msg in messages %}
        <div class="{{ msg.role }}">{{ msg.content }}</div>
        {% endfor %}
    </body>
    </html>
    """
    # 渲染并保存
```

---

## 三、实施路线图

### Phase 1（1-2 周）：核心增强
- [x] 扩展 Hook 事件系统（2.1）
- [ ] 实现会话树/分支（2.2）

### Phase 2（2-3 周）：多 Agent 支持
- [ ] 添加子 Agent 工具（2.3）
- [ ] 创建编排插件框架

### Phase 3（1-2 周）：用户体验
- [ ] 实时成本追踪（2.4）
- [ ] 键盘快捷键（2.5）
- [ ] 主题系统（2.6）

### Phase 4（可选）：高级功能
- [ ] RPC 模式（2.7）
- [ ] HTML 导出（2.8）
- [ ] 官方 SDK 示例库

---

## 四、总结

### Py Code Agent 的优势
✅ 优秀的 5 层自愈机制（Pi 没有）  
✅ 完善的插件管理系统（npm-like CLI）  
✅ MCP/A2A 网关支持  
✅ Skills 系统（兼容 Claude Code）  

### 主要差距
❌ UI/终端定制能力弱  
❌ Hook 事件粒度粗  
❌ 缺少多 Agent 原生支持  
❌ 会话管理能力有限  

### 关键建议
**优先实现 2.1（Hook 扩展）和 2.2（会话树）**，这两项是其他高级功能的基础。一旦有了细粒度的事件系统和灵活的会话管理，社区可以轻松开发各种扩展（如 Pi 的 13+ 扩展所示）。

---

## 附录：Pi 扩展灵感列表

以下是可以从 Pi 借鉴的扩展创意：

1. **Purpose Gate** - 启动时要求声明任务目标
2. **Damage Control** - 实时安全审计（危险命令拦截）
3. **Tool Counter Widget** - 实时显示各工具调用次数
4. **Cross-Agent** - 加载 Claude/Codex 的技能/命令
5. **Session Replay** - 可滚动的时间线回放
6. **Theme Cycler** - 快捷键切换主题
7. **TillDone** - 任务纪律系统（定义任务→跟踪进度）

这些都可以作为独立的 PyPI 插件包开发！
