# Py Code Agent 系统架构文档

本文档详细说明 Py Code Agent 的系统架构，帮助开发者理解整体设计和各模块职责。

---

## 1. 系统架构概览

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           CLI Layer (cli/)                              │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐  │
│   │   main   │  │   chat   │  │   run    │  │  config / plugin    │  │
│   └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────────┬───────────┘  │
└────────┼─────────────┼─────────────┼───────────────────┼──────────────┘
         │              │             │                   │
         ▼              ▼             ▼                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        Core Layer (core/)                              │
│   ┌────────────────────────────────────────────────────────────────┐  │
│   │                           Agent                                  │  │
│   │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │  │
│   │  │   Session   │  │   Events    │  │   PluginManager        │ │  │
│   │  └─────────────┘  └─────────────┘  └─────────────────────────┘ │  │
│   └────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
         │                                        │
         ▼                                        ▼
┌─────────────────────────────────┐   ┌──────────────────────────────────┐
│     LLM Layer (llm/)           │   │      Plugin System               │
│                                 │   │                                  │
│  ┌───────────────────────────┐ │   │  ┌────────────┐ ┌───────────────┐ │
│  │     LiteLLMProvider       │ │   │  │  Manager  │ │    Hooks      │ │
│  │  - stream()               │ │   │  │           │ │               │ │
│  │  - complete()            │ │   │  │ - load    │ │ - register    │ │
│  │  - Message/MessageRole   │ │   │  │ - health  │ │ - on_xxx     │ │
│  └───────────────────────────┘ │   │  │ - healing │ │ - get_system │ │
│                                 │   │  └────────────┘ └───────────────┘ │
└─────────────────────────────────┘   │                                   │
                                       │  Built-in Plugins:                 │
                                       │  - plan, skills, context          │
                                       │  - git, search, mcp_gateway       │
                                       │  - heartbeat, soul, a2a           │
                                       └───────────────────────────────────┘
         │                                        │
         ▼                                        ▼
┌─────────────────────────────────┐   ┌──────────────────────────────────┐
│     Channel Layer              │   │      Tools Layer                 │
│                                 │   │                                  │
│  ┌───────────────────────────┐ │   │  ┌──────────────┐ ┌─────────────┐ │
│  │   WebSocketChannel        │ │   │  │   BaseTool   │ │  Built-in   │ │
│  │  - get_channel_prompt()  │ │   │  │ - definition │ │ - read_file │ │
│  │  - get_channel_tools()   │ │   │  │ - execute() │ │ - write_file│ │
│  │  - receive() / send()    │ │   │  └──────────────┘ └─────────────┘ │
│  └───────────────────────────┘ │   │                                  │
│                                 │   │  ┌──────────────┐ ┌─────────────┐ │
│  ┌───────────────────────────┐ │   │  │    Skill     │ │  MCP Tools  │ │
│  │  WebSocketTransport      │ │   │  │   System     │ │             │ │
│  │  - aiohttp WebSocket     │ │   │  │  50+ skills │ │             │ │
│  └───────────────────────────┘ │   │  └──────────────┘ └─────────────┘ │
└─────────────────────────────────┘   └──────────────────────────────────┘
```

---

## 2. 模块职责

### 2.0 MCP Layer (`src/py_code_agent/mcp/`)

MCP (Model Context Protocol) 客户端实现，支持连接外部 MCP 服务器获取 10,000+ 工具。

| 文件 | 职责 |
|------|------|
| `types.py` | MCP 协议类型定义 (JSON-RPC 2.0 + MCP spec) |
| `transport.py` | StdioTransport 实现 (子进程 stdin/stdout 通信) |
| `client.py` | MCPClient 管理多服务器连接 |

**MCP 协议消息流程**:

```
Client ──initialize──> Server (JSON-RPC 2.0)
Client <─protocolVersion─ Server

Client ──tools/list──> Server
Client <─tools:[...]── Server

Client ──tools/call──> Server
Client <─content:[...]── Server
```

**工具暴露** (`mcp_gateway_plugin.py`):
- `mcp_list_servers` - 列出所有已连接服务器
- `mcp_call_tool` - 通用工具调用
- `mcp_{server}_{tool}` - 每个 MCP 工具的包装器

### 2.1 CLI Layer (`src/py_code_agent/cli/`)

| 文件 | 职责 |
|------|------|
| `main.py` | CLI 入口，定义 `pi-code-agent` 命令 |
| `app.py` | Streamlit Web UI 入口 |
| `config.py` | 配置管理命令 |
| `plugin.py` | 插件管理命令 |

**CLI 命令**:
```bash
pi-code-agent run "task"          # 运行单次任务
pi-code-agent chat                # 交互式对话
pi-code-agent config show         # 显示配置
pi-code-agent plugin list         # 列出插件
```

### 2.2 Core Layer (`src/py_code_agent/core/`)

| 文件 | 职责 |
|------|------|
| `agent.py` | Agent 主类，ReAct 循环执行 |
| `session.py` | 消息会话管理 |
| `events.py` | 事件系统 (START, CONTENT, TOOL_CALL, END) |

**Agent 核心流程** (`agent.py:170-300`):

```python
async def run(self, input: str) -> AsyncIterator[Event]:
    # 1. 初始化
    self.session.add_message(USER, input)
    yield START
    
    # 2. 循环直到完成或达到最大轮次
    while turn_count < max_turns:
        # 2.1 准备消息
        messages = self._prepare_messages()  # Base + Plugin prompts
        tools = self._prepare_tools()
        
        # 2.2 LLM 调用
        async for event in self.llm.stream(messages, tools):
            if event.type == CONTENT:
                assistant_content += event.data
            elif event.type == TOOL_CALL:
                assistant_tool_calls.append(event.data)
        
        # 2.3 执行工具
        for tc in assistant_tool_calls:
            result = await self._execute_tool(tc)
            self.session.add_message(TOOL, result)
        
        # 2.4 检查是否结束
        if not assistant_tool_calls:
            break
```

### 2.3 Plugin System (`src/py_code_agent/plugins/`)

#### 2.3.1 核心组件

| 文件 | 职责 |
|------|------|
| `manager.py` | 插件管理器：加载、健康检查、自愈 |
| `hooks.py` | Hook 规范定义 (pluggy) |
| `auto_repair.py` | 5层自愈机制 |

#### 2.3.2 Hook 类型

**Tool Hooks** (`hooks.py`):
| Hook | Signature | 用途 |
|------|-----------|------|
| `register_tools()` | `() -> List[BaseTool]` | 注册工具 |
| `before_tool_execute(tool_name, arguments)` | `(str, Dict)` | 工具执行前 |
| `after_tool_execute(tool_name, arguments, result)` | `(str, Dict, Any)` | 工具执行后 |
| `enhance_tool_error(tool_name, arguments, error_info)` | `(str, Dict, Dict) -> Optional[Dict]` | 错误分类与修复建议 |
| `enhance_tool_error_priority()` | `() -> int` | 优先级 (低=高优先级) |

**Agent Hooks** (`hooks.py`):
| Hook | Signature | 用途 |
|------|-----------|------|
| `on_agent_start(input)` | `(str) -> None` | Agent 启动 |
| `on_agent_end()` | `() -> None` | Agent 结束 |
| `on_llm_call(messages, tools)` | `(List, List) -> None` | LLM 调用前 |
| `on_llm_response(response)` | `(Any) -> None` | LLM 响应后 |
| `get_system_prompt()` | `() -> str` | 聚合系统提示词 |
| `on_plugin_heartbeat(event, data)` | `(str, Dict) -> None` | 统一心跳事件 |
| `get_capabilities()` | `() -> Dict` | 插件能力描述 |

**Hook 调用优先级** (`enhance_tool_error`):
- PlanPlugin: 10 (最高)
- SkillsPlugin: 20
- MCPGatewayPlugin: 30

#### 2.3.3 插件加载机制

**静态加载** (启动时):
```python
# manager.py:292-298
def load_plugins(self, plugin_dirs):
    self._load_from_entry_points()    # PyPI 包
    self._load_from_dir(plugin_dirs)  # 本地目录
    self._load_dependencies()         # 依赖解析
```

**动态加载** (运行时):
```python
# manager.py:345-375
def enable_plugin(self, name: str) -> bool:
    # 1. 从 builtin 目录加载
    # 2. 添加到启用列表
    # 3. 注册工具
```

#### 2.3.4 5 层自愈机制 (`auto_repair.py`)

| Layer | 场景 | 修复方式 |
|-------|------|----------|
| 1 | Hook 方法运行时崩溃 | try/except 包装 |
| 2 | 插件缺少 hook 方法 | 注入空方法 stub |
| 3 | ImportError (缺少包) | pip install 后重试 |
| 4 | AttributeError | 注入默认值 |
| 5 | Tool execute() 崩溃 | AST 补丁 + LLM 修复 |

**自愈流程**:
```
插件加载/Hook调用 ──> 错误检测 ──> 层级匹配 ──> 修复 ──> 重试
                                          │
                    ┌─────────────────────┼─────────────────────┐
                    ▼                     ▼                     ▼
              Layer 1-4              Layer 3              Layer 5
              (同步修复)           (pip install)        (AST/LLM)
```

#### 2.3.5 错误分类与修复建议

**Agent 错误分类** (`agent.py: _classify_error`):

| Error Type | 关键词 |
|------------|--------|
| `missing_dependency` | "command not found", "not installed", "no module named" |
| `permission_denied` | "permission denied", "access denied" |
| `invalid_arguments` | "invalid argument", "type error" |
| `network_timeout` | "timeout", "connection refused" |
| `skill_workflow_error` | "skill", "workflow", "plugin" |

**修复建议 Hook** (`enhance_tool_error`):

| Plugin | Priority | 错误类型 |
|--------|----------|----------|
| PlanPlugin | 10 | plan_task_json_error, plan_deadlock, subtask_timeout |
| SkillsPlugin | 20 | skill_not_found, docx_missing_dependency, pdf_missing_dependency |

### 2.4 LLM Layer (`src/py_code_agent/llm/`)

| 文件 | 职责 |
|------|------|
| `litellm_provider.py` | LiteLLM 统一接口 |

**支持的模型**:
- OpenAI (GPT-4, GPT-3.5)
- Anthropic (Claude)
- Azure OpenAI
- Ollama (本地)
- 100+ OpenAI 兼容 API

### 2.5 Channel Layer (`src/py_code_agent/channels/`)

| 文件 | 职责 |
|------|------|
| `__init__.py` | BaseChannel, ChannelMessage, ChannelResponse 定义 |
| `websocket.py` | WebSocket 通道实现 |
| `transport.py` | WebSocket 传输层 (aiohttp) |
| `cli.py` | CLI 通道实现 |

**Channel 消息格式**:

| 类型 | 字段 | 说明 |
|------|------|------|
| `message` | `message` | 普通文本消息 |
| `status` | `status` | 状态更新 (processing/thinking/done) |
| `file` | `file` | Base64 编码的文件内容 |

**Channel 工具** (WebSocket):
- `send_message`: 发送消息给用户
- `send_file`: 发送文件给用户 (Base64 编码)

### 2.6 Tools Layer (`src/py_code_agent/tools/`)

| 文件 | 职责 |
|------|------|
| `base.py` | BaseTool, ToolDefinition, ToolResult |
| `builtin.py` | 内置工具: read_file, write_file, execute_bash |

**工具执行流程**:
```python
# agent.py:260-300
async def _execute_tool(self, tool_call: dict):
    tool_name = tool_call["function"]["name"]
    arguments = json.loads(tool_call["function"]["arguments"])
    
    # 1. before_tool_execute hooks
    self.plugin_manager.call_before_tool_execute(tool_name, arguments)
    
    # 2. 执行
    tool = self.tools[tool_name]
    result = await tool.execute(**arguments)
    
    # 3. after_tool_execute hooks
    self.plugin_manager.call_after_tool_execute(tool_name, arguments, result)
    
    # 4. 错误增强
    if not result.success:
        self.plugin_manager.call_enhance_tool_error(tool_name, arguments, error)
```

### 2.6 Config Layer (`src/py_code_agent/config/`)

| 文件 | 职责 |
|------|------|
| `models.py` | Pydantic 配置模型 |
| `__init__.py` | 配置加载入口 |

**配置结构**:
```python
class Config(BaseModel):
    llm: LLMConfig          # 模型配置
    plugins: PluginConfig   # 插件配置
    react: ReActConfig      # ReAct 模式
    heartbeat: HeartbeatConfig  # 心跳配置
    # ...
```

---

## 3. 内置插件

### 3.1 插件列表

| 插件 | 文件 | 核心功能 |
|------|------|---------|
| **PlanPlugin** | `plan_plugin.py` | 任务规划、复杂任务检测 |
| **SkillsPlugin** | `skills_plugin.py` | 50+ 技能系统 |
| **ContextPlugin** | `context_plugin.py` | 上下文共享 |
| **GitPlugin** | `git_plugin.py` | Git 操作 |
| **SearchPlugin** | `search_plugin.py` | Web 搜索 |
| **MCPGatewayPlugin** | `mcp_gateway_plugin.py` | MCP 服务器网关 (10,000+ 工具) |
| **HeartbeatPlugin** | `heartbeat_plugin.py` | 心跳监控 |
| **SoulPlugin** | `soul_plugin.py` | Agent 个性 |
| **A2AGatewayPlugin** | `a2a_gateway_plugin.py` | Agent 间通信 |
| **LogPlugin** | `log_plugin.py` | 日志记录 |
| **AgentIdentityPlugin** | `agent_identity_plugin.py` | Agent 身份 |
| **PlanOrchestratorPlugin** | `plan_orchestrator.py` | 复杂任务编排 |

### 3.2 Skills 系统 (`skills_plugin.py`)

Skills 是可复用的工作流指令，存储在 SKILL.md 文件中。

**Skill 发现路径** (优先级从高到低):
1. `./.py-code-agent/skills/<name>/SKILL.md` (项目本地)
2. `~/.config/py-code-agent/skills/<name>/SKILL.md` (全局)
3. `~/.claude/skills/<name>/SKILL.md` (Claude Code 兼容)

**Skill 格式**:
```yaml
---
name: skill-name
description: 技能描述
---
# Skill Name
[完整工作流指令]
```

**提供工具**:
- `list_skills` - 列出所有可用技能
- `get_skill(name)` - 获取完整 SKILL.md 内容
- `search_skills(query)` - 关键词搜索
- `skill_<name>` - 每个 skill 的调用工具

**强制工作流**:
```
1. CALL: skill_xxx(skill_name='xxx')
2. WAIT: 返回显示 'MUST call get_skill'
3. CALL: get_skill('xxx')
4. READ: skill 内容作为工作流指南
5. EXECUTE: 按顺序执行工作流步骤
6. WRITE: 使用 write_file 写输出
7. VERIFY: 调用 task_done 验证
```

### 3.3 插件开发模板

```python
from py_code_agent.plugins.hooks import hookimpl, ToolHooks, AgentHooks
from py_code_agent.tools.base import BaseTool, ToolDefinition, ToolParameter, ToolParameterType, ToolResult

class MyPlugin(ToolHooks, AgentHooks):
    """Plugin description.

    Dependencies:
        - OtherPlugin (file:other): description
    """
    
    def __init__(self):
        self._agent_ref = None
    
    @hookimpl
    def register_tools(self) -> list[BaseTool]:
        return [MyTool(self)]
    
    @hookimpl
    def get_system_prompt(self) -> str:
        return """<plugin_depends>file:other</plugin_depends>

## My Plugin Guidelines
..."""
    
    @hookimpl
    def on_agent_start(self, input: str) -> None:
        pass


class MyTool(BaseTool):
    def __init__(self, plugin):
        self.plugin = plugin
    
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="my_tool",
            description="Do something",
            parameters=[...]
        )
    
    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult.ok(data=...)
```

---

## 4. 消息流程

### 4.1 CLI → Agent

```
用户输入: "实现用户登录系统"
         │
         ▼
cli/main.py: run() command
         │
         ▼
Agent(config).run(input)
         │
         ▼
session.add_message(USER, input)
```

### 4.2 Agent → LLM

```
messages = [
    {"role": "system", "content": BASE_PROMPT + PLUGIN_PROMPTS},
    {"role": "user", "content": "实现用户登录系统"},
    {"role": "assistant", "content": "Thought: ..."},
    {"role": "tool", "content": "tool result...", "tool_call_id": "..."},
]
         │
         ▼
llm.stream(messages, tools)
         │
         ▼
LLM Response (streaming)
```

### 4.3 Tool Execution

```
LLM: {"tool_calls": [{"function": {"name": "read_file", "arguments": "..."}}]}
         │
         ▼
agent._execute_tool()
         │
         ├─→ before_tool_execute hooks
         ├─→ read_file.execute()
         ├─→ after_tool_execute hooks
         └─→ error? → enhance_tool_error hooks
```

---

## 5. 关键文件索引

### 5.1 核心

| 文件 | 关键类/函数 | 行号 |
|------|------------|------|
| `core/agent.py` | `Agent.run()` | 170 |
| `core/agent.py` | `Agent._classify_error()` | 错误分类 |
| `core/agent.py` | `Agent._prepare_messages()` | 318 |
| `core/agent.py` | `Agent._execute_tool()` | 330 |
| `core/session.py` | `Session` | 会话管理 |
| `core/events.py` | `Event`, `EventType` | 事件类型 |

### 5.2 MCP 系统

| 文件 | 关键类/函数 | 用途 |
|------|------------|------|
| `mcp/types.py` | `MCPTool`, `MCPErrorCode` | 协议类型 |
| `mcp/transport.py` | `StdioTransport` | 子进程通信 |
| `mcp/client.py` | `MCPClient` | 多服务器管理 |
| `mcp_gateway_plugin.py` | `MCPGatewayPlugin` | 工具暴露 |

### 5.3 插件系统

| 文件 | 关键类/函数 | 行号 |
|------|------------|------|
| `plugins/manager.py` | `PluginManager.load_plugins()` | 插件加载 |
| `plugins/manager.py` | `PluginManager.register_tools()` | 工具注册 |
| `plugins/manager.py` | `PluginManager.call_get_system_prompt()` | 提示词聚合 |
| `plugins/manager.py` | `PluginManager.enable_plugin()` | 动态启用 |
| `plugins/hooks.py` | `ToolHooks`, `AgentHooks` | Hook 规范 |
| `plugins/auto_repair.py` | `AiAutoRepair` | 5 层自愈 |

### 5.4 工具

| 文件 | 关键类/函数 | 行号 |
|------|------------|------|
| `tools/base.py` | `BaseTool` | 60 |
| `tools/base.py` | `ToolDefinition` | 32 |
| `tools/base.py` | `ToolResult` | 43 |
| `tools/builtin.py` | `ReadFileTool` | 17 |
| `tools/builtin.py` | `WriteFileTool` | 100 |
| `tools/builtin.py` | `ExecuteBashTool` | 200 |

### 5.5 LLM

| 文件 | 关键类/函数 | 行号 |
|------|------------|------|
| `llm/litellm_provider.py` | `LiteLLMProvider.stream()` | 85 |
| `llm/litellm_provider.py` | `LiteLLMProvider.complete()` | 110 |
| `llm/litellm_provider.py` | `Message`, `MessageRole` | 17 |

### 5.6 配置

| 文件 | 关键类/函数 | 行号 |
|------|------------|------|
| `config/models.py` | `Config` | 100 |
| `config/models.py` | `LLMConfig` | 46 |
| `config/models.py` | `PluginConfig` | 119 |

---

## 6. 扩展开发指南

### 6.1 添加新工具

1. 在 `tools/builtin.py` 或插件中继承 `BaseTool`
2. 实现 `definition` 属性和 `execute()` 方法
3. 通过插件的 `register_tools()` 注册

### 6.2 添加新插件

1. 在 `plugins/builtin/` 创建 `xxx_plugin.py`
2. 继承 `ToolHooks`, `AgentHooks`
3. 实现必要的 hook 方法
4. 在 `config.yaml` 的 `plugins.enabled` 中启用

### 6.3 添加新技能

1. 在 `~/.claude/skills/` 创建目录
2. 添加 `SKILL.md` 文件
3. 使用 `skills_plugin.py` 的工具调用

---

## 7. 配置示例

### 7.1 最小配置 (config.yaml)

```yaml
llm:
  model: gpt-4
  api_key: ${OPENAI_API_KEY}

plugins:
  enabled:
    - file:log
    - file:skills
    - file:plan
    - file:context
```

### 7.2 完整配置

```yaml
llm:
  provider: openai
  model: gpt-4
  api_key: ${OPENAI_API_KEY}
  temperature: 0.7
  max_tokens: 4096

react:
  enabled: true
  max_turns: 10

plugins:
  enabled:
    - file:log
    - file:soul
    - file:agent_identity
    - file:skills
    - file:plan
    - file:context
    - file:heartbeat
  disabled: []

heartbeat:
  enabled: true
  interval: 30
  timeout: 90
```
