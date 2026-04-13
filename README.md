# Py Code Agent

AI coding assistant with ReAct reasoning, pluggable architecture, and 5-layer self-healing. Powered by LiteLLM for 100+ model providers.

## 🚀 Features

- **🤖 Multi-LLM Support**: 100+ providers via **LiteLLM** (OpenAI, Anthropic, Azure, Ollama, etc.)
- **🧠 ReAct Reasoning**: Thought → Action → Observation loop for autonomous task execution
- **🔌 Plugin System**: pluggy-based extensible architecture with **5-layer self-healing**
  - **30+ Hook Events**: Message streaming, tool execution flow, session tree operations, model switching
  - **Extension APIs**: Register commands, shortcuts, CLI flags, UI components, custom providers
- **🌐 Channel System**: CLI, WebSocket, JSON, RPC, and pluggable transport channels
- **🧩 Skills System**: Claude Code-compatible skill loading from `SKILL.md` files
- **🔗 MCP Gateway**: Connect to 10,000+ tools via Model Context Protocol servers
- **🤝 A2A Protocol**: Agent-to-agent communication via A2A v0.3.0
- **📦 Package Management**: npm-like plugin install/enable/disable/search via CLI
- **🛡️ Error Enhancement**: intelligent error classification with automatic fix suggestions
- **✅ Task Verification**: `task_done` verifies actual file output against expected results
- **🌳 Session Tree**: Branch/fork sessions, navigate conversation history with `/tree`, `/fork`, `/switch`
- **💰 Cost Tracking**: Real-time token usage and cost estimation per request

## 📦 Installation

### No Install — uvx (Recommended)

```bash
uvx py-code-agent chat
uvx py-code-agent chat --model gpt-4
uvx py-code-agent run "Hello world"
```

> **Note**: `uvx` requires `uv`. Install via: `curl -LsSf https://astral.sh/uv/install.sh | sh`

### From PyPI

```bash
pip install py-code-agent
pip install py-code-agent[all]   # all optional dependencies
pip install py-code-agent[dev]    # dev dependencies
pip install py-code-agent[gateway]  # MCP/A2A gateway support
```

### From Source

```bash
git clone https://github.com/bonashen/py-code-agent.git
cd py-code-agent
pip install -e .
```

## 🚀 Quick Start

### 1. Configure API Key

```bash
# OpenAI
export PY_LLM_API_KEY=sk-...

# Anthropic
export PY_LLM_API_KEY=sk-ant-...

# Azure OpenAI
export PY_LLM_API_KEY=...
export PY_LLM_BASE_URL=https://your-resource.openai.azure.com

# Or via .env file (auto-loaded from project root)
echo "PY_LLM_API_KEY=sk-..." > .env
```

### 2. Start Interactive Chat

```bash
py-code-agent chat --model gpt-4
py-code-agent chat --model claude-3-opus
py-code-agent chat --model ollama/llama2   # local Ollama
```

### 3. Run a Single Task

```bash
py-code-agent run "Create a Python script that prints the Fibonacci sequence"
```

### 4. Session Management (Tree/Branch)

```bash
# In chat mode, use slash commands:
> /tree                    # View session tree structure
> /fork "New branch name"  # Create a branch from current point
> /switch <node-id>        # Switch to a different session node
```

### 5. Start WebSocket Server

```bash
py-code-agent channel websocket --port 8080 --no-auth
```

### 6. JSON/RPC Mode (for programmatic access)

```bash
# JSON mode - output as JSON
py-code-agent run --mode json "Fix the bug in main.py"

# RPC mode - JSONL over stdin/stdout
py-code-agent channel rpc --port 9000
```

## 🔧 Configuration

Config file resolution order (first found wins):
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

react:
  enabled: true
  max_turns: 10

plugins:
  enabled: []
  disabled: []
```

### Config CLI

```bash
py-code-agent config get llm.model
py-code-agent config set llm.model gpt-4
py-code-agent config list
py-code-agent config path
py-code-agent config init
py-code-agent config set llm.api_key sk-xxx --global
py-code-agent config set llm.model gpt-4 --local
```

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        CLI Layer                            │
│   chat │ run │ config │ plugin │ channel websocket/rpc     │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│                      Core Layer                             │
│   Agent (ReAct loop) → Session Tree → Events (30+)         │
│                              ↓                               │
│                     PluginManager (5-layer repair)          │
└──────────┬──────────────────────────┬───────────────────────┘
           │                          │
┌──────────▼──────────┐   ┌───────────▼───────────────────────┐
│    LLM Layer        │   │         Plugin System             │
│  LiteLLMProvider    │   │  Manager + 5-layer auto-repair    │
│  stream/complete    │   │  30+ hooks across 6 categories    │
│  cost tracking      │   │  Built-in + Local + Global + PyPI │
└─────────────────────┘   └───────────┬───────────────────────┘
                                      │
                    ┌─────────────────┼───────────────────────┐
                    │                 │                       │
        ┌───────────▼──────┐ ┌────────▼───────┐  ┌──────────▼──────────┐
        │  Extension APIs  │ │  Hook Events   │  │   Session Commands  │
        │ register_command │ │ message_*      │  │ /tree /fork /switch │
        │ register_shortcut│ │ tool_*_flow    │  │ session compression │
        │ register_flag    │ │ session_tree   │  │ cost tracking       │
        │ register_widget  │ │ model_switch   │  │                     │
        └──────────────────┘ └────────────────┘  └─────────────────────┘
                                      │
┌─────────────────────────────────────▼───────────────────────┐
│                    Tools + Channels                         │
│  read_file │ write_file │ execute_bash │ task_done          │
│  WebSocket │ CLI │ JSON │ RPC │ pluggable transports       │
│  MCP Gateway (10,000+ tools) │ A2A Protocol               │
└─────────────────────────────────────────────────────────────┘
```

## 🔌 Plugin System

### Hook System (30+ Events)

The plugin system now supports **30+ hook events** across 6 categories:

| Category | Hooks | Description |
|----------|-------|-------------|
| **LifecycleHooks** | `before_session`, `after_session`, `before_turn`, `after_turn` | Session and turn lifecycle |
| **MessageHooks** | `message_start`, `message_update`, `message_end` | Streaming message events |
| **ToolHooks** | `tool_execution_start`, `tool_execution_update`, `tool_execution_end` | Tool execution flow |
| **SessionHooks** | `before_tree`, `tree`, `before_fork`, `fork`, `before_switch`, `switch`, `before_compact`, `compacted` | Session tree operations |
| **ModelHooks** | `model_select`, `before_model_switch`, `after_model_switch` | Model selection and switching |
| **ExtensionHooks** | `register_commands`, `register_shortcuts`, `register_flags`, `register_widgets`, `register_providers` | Extension registration |

### Built-in Plugins

| Plugin Name | Class | Description |
|-------------|-------|-------------|
| `file:soul` | SoulPlugin | Agent personality — loads `soul.md` |
| `file:agent_identity` | AgentIdentityPlugin | Agent self-awareness — loads `agent.md` |
| `file:plan` | PlanPlugin | Complex task planning with mandatory rules |
| `file:skills` | ClaudeSkillsPlugin | Loads Claude Code skills from `SKILL.md` |
| `file:context` | ContextPlugin | Context sharing across turns |
| `file:heartbeat` | HeartbeatPlugin | Real-time agent status monitoring |
| `file:log` | LogPlugin | Logs tool/agent lifecycle events |
| `file:edit_file` | EditFilePlugin | File editing operations |

### External Plugins

| Plugin | Description |
|--------|-------------|
| `py-code-agent-git` | Git status and operations |
| `py-code-agent-search` | Web search via DuckDuckGo |
| `py-code-agent-mcp-gateway` | MCP server connections (10,000+ tools) |
| `py-code-agent-a2a-gateway` | Agent-to-agent communication (A2A v0.3.0) |
| `py-code-agent-omo` | OMO mode: subagent dispatch, intent gate, category routing |
| `py-code-agent-grep` | Code search engine (text + AST) |
| `py-code-agent-plan-orchestrator` | Advanced task orchestration |

### Plugin Directory Structure

Plugins are loaded from four tiers (first match wins).

| Tier | Directory | Purpose |
|------|-----------|---------|
| Built-in | `<repo>/plugins/builtin/` | Shipped with package |
| Local | `./.py-code-agent/plugins/` | Project-specific |
| Global | `~/.config/py-code-agent/plugins/` | User-wide |
| Entry Points | PyPI packages | Community plugins |

### Plugin Self-Healing

5 layers of auto-repair with **100% hook coverage** (30/30 hooks protected).

| Layer | Scenario | Fix |
|-------|----------|-----|
| 1 | Hook method crashes | Wrap with `try/except` at runtime |
| 2 | Plugin missing hook methods | Inject no-op stubs |
| 3 | Import errors (missing packages) | `pip install` then retry |
| 4 | Attribute errors | Inject missing attributes |
| 5 | Tool `execute()` crashes | AST-patch source file + reload |

**Coverage**: All 30 hooks across 6 categories are protected by the auto-repair system.

### CLI Plugin Management

```bash
# List all available plugins
py-code-agent plugin available

# Enable / Disable
py-code-agent plugin enable file:soul
py-code-agent plugin disable file:search

# Search & Install
py-code-agent plugin search web-search
py-code-agent plugin install py-code-agent-some-plugin
py-code-agent plugin install git+https://github.com/user/repo.git

# List / Uninstall
py-code-agent plugin list
py-code-agent plugin uninstall py-code-agent-some-plugin

# Scaffold new plugin
py-code-agent plugin init my-awesome-plugin
```

## 🧠 ReAct Mode

When `react.enabled: true`, the agent follows a **Thought → Action → Observation** loop:

1. **Thought**: The LLM reasons about what to do next
2. **Action**: The LLM calls a tool (or provides a final answer)
3. **Observation**: The tool result is fed back as context
4. Repeat until `task_done` is called or max turns reached

This enables autonomous coding — the agent can write files, run tests, fix errors, and iterate until the task is complete.

## 🌐 Channel System

Channels provide pluggable transport for agent communication with **4 modes**:

### CLI Channel

Interactive terminal via `py-code-agent chat`.

**Slash Commands:**
- `/tree` - View session tree structure
- `/fork <name>` - Create a branch from current point
- `/switch <node-id>` - Switch to a different session node
- `/compact` - Manually trigger context compression

### WebSocket Channel

```bash
py-code-agent channel websocket --port 8080 --api-key your-secret-key
```

Message format:
```json
{ "type": "message", "content": "Hello, agent!" }
```

Response:
```json
{ "type": "response", "content": "Hello! How can I help?", "status": "done" }
```

### JSON Mode

For programmatic access with structured output:

```bash
py-code-agent run --mode json "Fix the bug in main.py"
```

Output:
```json
{
  "thought": "I need to examine main.py first...",
  "action": "read_file",
  "observation": "...",
  "final_answer": "Bug fixed!"
}
```

### RPC Mode

JSONL over stdin/stdout for embedding in other applications:

```bash
# Start RPC server
py-code-agent channel rpc --port 9000

# Or pipe commands
echo '{"type": "message", "content": "Hello"}' | py-code-agent channel rpc
```

### Custom Channels

Implement `BaseChannel` interface:
- `get_channel_prompt()` — context injection
- `get_channel_tools()` — channel-specific tools
- `receive()` — async message iterator
- `send(response)` — send responses

## 🧩 Skills System

Skills are reusable workflows stored in `SKILL.md` files, compatible with Claude Code.

**Discovery paths** (highest priority first):
1. `./.py-code-agent/skills/<name>/SKILL.md`
2. `~/.config/py-code-agent/skills/<name>/SKILL.md`
3. `~/.claude/skills/<name>/SKILL.md`

```bash
# List available skills
> list_skills

# Get skill content
> get_skill(name="frontend-design")
```

## 🛠️ Development

```bash
git clone https://github.com/bonashen/py-code-agent.git
cd py-code-agent
pip install -e ".[dev,all]"

# Run tests
pytest

# Format code
black src/ tests/

# Lint
ruff check src/ tests/

# Type check
mypy src/
```

### Project Structure

```
py-code-agent/
├── src/py_code_agent/       # Main package
│   ├── core/                # Agent, Session, Events
│   ├── cli/                 # CLI commands (chat, run, config, plugin)
│   ├── channels/            # Transport channels (CLI, WebSocket)
│   ├── llm/                 # LiteLLM provider
│   ├── tools/               # BaseTool + built-in tools
│   ├── plugins/             # Plugin manager, hooks, auto-repair
│   ├── mcp/                 # MCP client (types, transport)
│   ├── config/              # Pydantic config models
│   └── utils/               # Helpers
├── plugins/builtin/         # Built-in plugins
├── external-plugins/        # External plugin packages
├── tests/                   # Test suite
└── docs/                    # Documentation
```

## 🤝 Contributing

We welcome all contributions! See [CONTRIBUTING.md](CONTRIBUTING.md).

## 📄 License

MIT License — see [LICENSE](LICENSE).

## 🙏 Acknowledgements

- [LiteLLM](https://github.com/BerriAI/litellm) — unified LLM API
- [Rich](https://github.com/Textualize/rich) — terminal output
- [Textual](https://github.com/Textualize/textual) — TUI framework
- [Pydantic](https://github.com/pydantic/pydantic) — data validation
- [pluggy](https://github.com/pytest-dev/pluggy) — plugin hooks

---

<p align="center">
  Made with ❤️ by the Py Code Agent Team
</p>
