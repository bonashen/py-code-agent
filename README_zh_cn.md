# Py Code Agent

一个强大的 AI 编程助手。

## 🚀 功能特性

- **🤖 多 LLM 支持**: 通过 **LiteLLM** 支持 100+ LLM 提供商（OpenAI、Anthropic、Azure、Ollama 等）
- **🛠️ 内置工具**: 文件操作、代码搜索、带路径验证的 bash 执行
- **💬 交互式 CLI**: 基于 Rich 和 Textual 的终端 UI
- **🔌 插件系统**: 基于 pluggy 的可扩展架构，5 层自愈机制，内置 + 本地 + 全局 + PyPI 插件
- **🧠 灵魂与身份**: 通过插件配置 Agent 的人格、语气和行为价值观
- **📦 包管理**: 通过 CLI 实现类似 npm 的插件安装体验
- **🔍 错误增强系统**: 智能错误分类，自动注入修复建议
- **✅ 任务验证**: `task_done` 通过检查文件系统验证实际文件输出
- **📋 强制规划**: 复杂任务必须通过 PlanPlugin 先调用 `plan_task`

## 📦 安装

### 无需安装 — uvx（推荐）

```bash
# 直接运行，无需安装
uvx py-code-agent chat
uvx py-code-agent chat --model gpt-4
uvx py-code-agent run "Hello world"
```

> **注意**: `uvx` 需要安装 `uv`。安装方式: `curl -LsSf https://astral.sh/uv/install.sh | sh`

### 从 PyPI 安装

```bash
pip install py-code-agent
pip install py-code-agent[all]   # 所有可选依赖
pip install py-code-agent[dev]    # 开发依赖
```

### 从源码安装

```bash
git clone https://github.com/bonashen/py-code-agent.git
cd py-code-agent
pip install -e .
```

## 🚀 快速开始

### 1. 配置 API Key

```bash
# OpenAI
export PY_LLM_API_KEY=sk-...

# Anthropic
export PY_LLM_API_KEY=sk-ant-...

# Azure OpenAI
export PY_LLM_API_KEY=...
export PY_LLM_BASE_URL=https://your-resource.openai.azure.com

# 或通过 .env 文件（自动从项目根目录加载）
echo "PY_LLM_API_KEY=sk-..." > .env
```

### 2. 启动交互式对话

```bash
pi-code-agent chat --model gpt-4
pi-code-agent chat --model claude-3-opus
pi-code-agent chat --model ollama/llama2   # 本地 Ollama
```

### 3. 运行单个任务

```bash
pi-code-agent run "创建一个打印斐波那契数列的 Python 脚本"
```

## 🔧 配置

配置文件查找顺序（优先使用先找到的）:
1. `~/.config/py-code-agent/config.yaml`
2. `./.py-code-agent/config.yaml`

```yaml
llm:
  provider: ${PY_LLM_PROVIDER:-openai}
  model: ${PY_LLM_MODEL:-gpt-4}
  api_key: ${PY_LLM_API_KEY}
  base_url: ${PY_LLM_BASE_URL:-http://localhost:8000/v1}
  timeout: ${PY_LLM_TIMEOUT:-300}
  temperature: ${PY_LLM_TEMPERATURE:-0.7}
  max_tokens: ${PY_LLM_MAX_TOKENS:-4000}
  debug: ${PY_LLM_DEBUG:-false}
  verbose: ${PY_LLM_VERBOSE:-false}

tools:
  enabled:
    - read_file
    - write_file
    - execute_bash
  timeout: ${PY_TOOLS_TIMEOUT:-30}
  allow_bash: ${PY_TOOLS_ALLOW_BASH:-true}
  allowed_paths:
    - ./
  blocked_paths:
    - ~/.ssh
    - ~/.aws

ui:
  theme: dark
  show_tool_calls: true
  stream_output: true
  history_size: 1000

plugins:
  enabled: []
  disabled: []
```

### 配置命令

```bash
# 获取配置值
pi-code-agent config get llm.model

# 设置配置值
pi-code-agent config set llm.model gpt-4
pi-code-agent config set llm.temperature 0.5

# 列出所有配置项
pi-code-agent config list

# 删除配置项
pi-code-agent config unset plugins.disabled

# 显示当前配置文件路径
pi-code-agent config path

# 创建默认配置
pi-code-agent config init

# 指定配置文件
pi-code-agent config set llm.api_key sk-xxx --global
pi-code-agent config set llm.model gpt-4 --local
```

## 🔌 插件系统

### 内置插件

| 插件名 | 类 | 描述 |
|-------------|-------|-------------|
| `file:soul` | SoulPlugin | Agent 人格 — 加载 `soul.md` |
| `file:agent_identity` | AgentIdentityPlugin | Agent 自我认知 — 加载 `agent.md` |
| `file:git` | GitStatusPlugin | Git 状态和操作 |
| `file:search` | SearchPlugin | 通过 DuckDuckGo 网络搜索 |
| `file:log` | LogPlugin | 记录工具/Agent 生命周期事件 |
| `file:skills` | ClaudeSkillsPlugin | 从 `SKILL.md` 加载 Claude Code 技能 |
| `file:plan` | PlanPlugin | 强制规划的复杂任务规划 |
| `file:heartbeat` | HeartbeatPlugin | 实时 Agent 状态监控 |
| `file:mcp_gateway` | MCPGatewayPlugin | 连接 MCP 服务器 |
| `file:a2a_gateway` | A2AGatewayPlugin | Agent 间通信 |

### 灵魂插件

配置 Agent 的人格、语气和行为价值观。

```bash
# 查看当前灵魂
> get_soul

# 动态更新灵魂
> update_soul(content="你是一个简洁务实的资深工程师...")

# 列出内置模板
> list_soul_templates
```

内置模板: `default`、`creative`、`analytical`、`senior_engineer`

灵魂文件查找顺序（优先使用先找到的）:
1. `./.py-code-agent/soul.md` (项目本地 — 最高优先级)
2. `~/.config/py-code-agent/soul.md` (全局配置)
3. `~/.claude/soul.md` (用户目录 — 备用)

### 心跳插件

外部可观测性的实时 Agent 状态监控。

```bash
> get_heartbeat_status
```

提供:
- **任务进度**: 跟踪当前任务、子任务、完成百分比
- **工具调用**: 记录所有工具调用的时间戳
- **错误**: 捕获并报告错误及修复建议
- **审计日志**: 滚动事件缓冲区（可配置，默认 1000 条）
- **活动**: 显示最后活动时间、空闲状态、LLM 调用次数

### MCP 网关插件

连接 MCP 服务器以获取 10,000+ 工具。

```yaml
# config.yaml
plugins:
  gateway:
    mcp:
      servers:
        - name: filesystem
          command: npx
          args: ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
        - name: postgres
          command: npx
          args: ["-y", "@modelcontextprotocol/server-postgres", "postgresql://user:pass@host/db"]
```

工具: `mcp_list_servers`, `mcp_call_tool`, `mcp_{server}_{tool}`

需要: `pip install py-code-agent[gateway]`

### A2A 网关插件

通过 A2A v0.3.0 协议进行 Agent 间通信。

```yaml
# config.yaml
plugins:
  gateway:
    a2a:
      host: "0.0.0.0"
      port: 18800
      name: "MyAgent"
      description: "我的 AI 编程助手"
```

端点:
- `GET /.well-known/agent-card.json` — Agent 发现
- `POST /a2a/jsonrpc` — JSON-RPC 消息

工具: `a2a_list_peers`, `a2a_send_message`, `a2a_get_my_card`

需要: `pip install py-code-agent[gateway]`

### CLI 插件管理

```bash
# 列出所有可用插件
pi-code-agent plugin available

# 启用插件
pi-code-agent plugin enable file:soul

# 禁用插件
pi-code-agent plugin disable file:search

# 在 PyPI 搜索插件
pi-code-agent plugin search web-search

# 从 PyPI 安装
pi-code-agent plugin install py-code-agent-some-plugin

# 从 git 或本地路径安装
pi-code-agent plugin install git+https://github.com/user/repo.git

# 列出所有已安装插件
pi-code-agent plugin list

# 卸载
pi-code-agent plugin uninstall py-code-agent-some-plugin

# 脚手架创建新插件
pi-code-agent plugin init my-awesome-plugin
```

### 插件目录结构

插件从四个层级加载（优先使用先找到的）。

| 层级 | 目录 | 用途 |
|------|-----------|---------|
| 内置 | `<repo>/plugins/builtin/` | 随包分发 |
| 本地 | `./.py-code-agent/plugins/` | 项目专用 |
| 全局 | `~/.config/py-code-agent/plugins/` | 用户级别 |
| 入口点 | PyPI 包 | 社区插件 |

### 插件自愈机制

5 层自动修复。

| 层级 | 场景 | 修复 |
|-------|----------|-----|
| 1 | Hook 方法崩溃 | 运行时包装 try/except |
| 2 | 插件缺少 hook 方法 | 注入空操作存根 |
| 3 | 导入错误（缺少包） | pip install 后重试 |
| 4 | 属性错误 | 注入缺失属性 |
| 5 | 工具 execute() 崩溃 | AST 修补源文件 + 重载 |

## 🛠️ 开发

```bash
git clone https://github.com/bonashen/py-code-agent.git
pip install -e ".[dev,all]"

# 运行测试
pytest

# 格式化代码
black src/ tests/

# 代码检查
ruff check src/ tests/

# 类型检查
mypy src/
```

## 🤝 贡献

欢迎所有贡献！参见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 📄 许可证

MIT License — 参见 [LICENSE](LICENSE)。

## 🙏 致谢

- [LiteLLM](https://github.com/BerriAI/litellm) — 统一 LLM API
- [Rich](https://github.com/Textualize/rich) — 终端输出
- [Textual](https://github.com/Textualize/textual) — TUI 框架
- [Pydantic](https://github.com/pydantic/pydantic) — 数据验证
- [pluggy](https://github.com/pytest-dev/pluggy) — 插件钩子

---

<p align="center">
  由 Py Code Agent 团队用 ❤️ 打造
</p>
