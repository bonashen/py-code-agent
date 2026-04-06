# Data Flow Path: From File Loading to Final Usage

This document traces the complete path of how a request flows through the Py Code Agent system, from configuration file loading through processing to final tool execution.

## Overview

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Config File    │────▶│  Config Models  │────▶│  Agent Init     │
│  (config.yaml)  │     │  (Pydantic)     │     │                 │
└─────────────────┘     └─────────────────┘     └────────┬────────┘
                                                       │
                                                       ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Tool Results   │◀────│  Tool Execution │◀────│  LLM Stream     │
│  (Output)       │     │  (read_file,    │     │  (Async Gen)    │
└─────────────────┘     │  write_file...) │     └─────────────────┘
                        └─────────────────┘
```

---

## Phase 1: Configuration File Loading

### 1.1 Entry Point - CLI Main
**File:** `src/py_code_agent/cli/main.py`

```python
@cli.command()
@click.option("--config", "-c", type=click.Path(), help="Configuration file path")
def cli(ctx: click.Context, config: Optional[str]) -> None:
    # Load configuration
    if config:
        ctx.obj["config"] = Config.from_file(config)
    else:
        ctx.obj["config"] = Config.from_env()
```

### 1.2 Configuration Loading - Config Models
**File:** `src/py_code_agent/config/models.py`

The `Config.from_file()` method handles the complete loading process:

```python
@classmethod
def from_file(cls, path: str, load_env: bool = True) -> "Config":
    # Step 1: Load .env file first if requested
    if load_env:
        load_env_file()

    # Step 2: Read the YAML config file
    config_path = Path(path).expanduser()
    with open(config_path, "r", encoding="utf-8") as f:
        raw_content = f.read()

    # Step 3: Expand ${VAR:-default} environment variables
    expanded_content = _expand_env_vars_in_content(raw_content)
    
    # Step 4: Parse YAML into Python dict
    data = yaml.safe_load(expanded_content)

    # Step 5: Create Config instance with Pydantic validation
    return cls(**data)
```

### 1.3 Environment Variable Expansion
**File:** `src/py_code_agent/config/models.py`

Environment variable substitution supports:
- `${VAR}` - use env var, empty string if unset
- `${VAR:-default}` - use env var, fallback to 'def' if unset

```python
def _expand_env_vars_in_content(content: str) -> str:
    def replacer(m: re.Match) -> str:
        var = m.group("var")
        raw_def = m.group("def")
        default = raw_def.lstrip("-") if raw_def else ""
        return os.environ.get(var, default)

    pattern = r"\$\{(?P<var>[A-Za-z_][A-Za-z0-9_]*)(?:[:-](?P<def>[^}]*))?\}"
    return re.sub(pattern, replacer, content)
```

---

## Phase 2: Agent Initialization

### 2.1 Agent Creation
**File:** `src/py_code_agent/core/agent.py`

When `Agent(config)` is instantiated:

```python
class Agent:
    def __init__(self, config: Config):
        self.config = config
        self.agent_id = str(uuid.uuid4())
        self.session = Session()
        
        # Initialize LLM provider
        model = config.llm.model
        if config.llm.base_url and not model.startswith(...):
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
        
        # Initialize tools
        self.tools: Dict[str, Any] = {}
        self._register_builtin_tools()
        self._setup_plugins()
```

### 2.2 Tool Registration
**File:** `src/py_code_agent/core/agent.py`

Built-in tools are registered during initialization:

```python
def _register_builtin_tools(self) -> None:
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
```

---

## Phase 3: Processing Loop (Run Cycle)

### 3.1 Main Run Method
**File:** `src/py_code_agent/core/agent.py`

The `run()` method implements the main ReAct loop:

```python
async def run(self, input: str) -> AsyncIterator[Event]:
    # Add user message to session
    self.session.add_message(MessageRole.USER, input)
    
    # Signal start
    yield Event(type=EventType.START, data={"input": input})
    
    # Get ReAct configuration
    react_enabled = self.config.react.enabled
    max_turns = self.config.react.max_turns
    turn_count = 0
    
    # Main loop
    while turn_count < max_turns:
        turn_count += 1
        
        # Prepare messages and tools
        messages = self._prepare_messages()
        tools = self._prepare_tools()
        
        # Stream LLM response
        assistant_content = ""
        assistant_tool_calls = []
        
        async for event in self.llm.stream(...):
            if event.type == EventType.CONTENT:
                assistant_content += event.data.get("content", "")
                yield event
            elif event.type == EventType.TOOL_CALL:
                assistant_tool_calls.append(event.data)
```

### 3.2 Tool Execution Flow

```python
# Process each tool call
for tc in assistant_tool_calls:
    tool_name = tc["function"]["name"]
    tool_args = tc["function"]["arguments"]
    
    # Execute the tool
    tool_result = await self._execute_tool(tc)
    
    # Build observation and add to session
    obs_content = self._build_observation(tool_result, tool_name, tool_args)
    self.session.add_message(MessageRole.TOOL, obs_content, ...)
    
    # Yield tool result event
    yield Event(type=EventType.TOOL_RESULT, data=tool_result)
```

---

## Phase 4: Tool Execution (read_file Example)

### 4.1 Tool Definition
**File:** `src/py_code_agent/tools/builtin.py`

```python
class ReadFileTool(BaseTool):
    def __init__(self, allowed_paths=None, blocked_paths=None):
        self.allowed_paths = [Path(p).expanduser().resolve() for p in (allowed_paths or [])]
        self.blocked_paths = [Path(p).expanduser().resolve() for p in (blocked_paths or [])]

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="read_file",
            description="Read file content with optional line range",
            parameters=[
                ToolParameter(name="path", type=ToolParameterType.STRING, required=True),
                ToolParameter(name="offset", type=ToolParameterType.INTEGER, default=1),
                ToolParameter(name="limit", type=ToolParameterType.INTEGER, default=100),
            ]
        )
```

### 4.2 Tool Execution Steps

```python
async def execute(self, path: str, offset: int = 1, limit: int = 100) -> ToolResult:
    try:
        # Step 1: Resolve path
        file_path = Path(path).expanduser().resolve()
        
        # Step 2-5: Validate
        if not file_path.exists():
            return ToolResult.fail(f"File not found: {path}")
        # ... blocked/allowed path checks ...
        if not file_path.is_file():
            return ToolResult.fail(f"Path is not a file: {path}")
        
        # Step 6-8: Read and process
        async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
            content = await f.read()
            lines = content.split("\n")
            start_idx = max(0, offset - 1)
            end_idx = min(len(lines), start_idx + limit)
            selected_lines = lines[start_idx:end_idx]
            numbered_lines = [f"{i}: {line}" for i, line in enumerate(selected_lines, start=start_idx + 1)]
            result_content = "\n".join(numbered_lines)
            
            # Step 9: Return result
            return ToolResult.ok(
                data={
                    "content": result_content,
                    "path": str(file_path),
                    "offset": start_idx + 1,
                    "lines_read": len(selected_lines),
                    "total_lines": len(lines)
                },
                summary=f"Read {len(selected_lines)} lines from {file_path.name}"
            )
    except Exception as e:
        return ToolResult.fail(f"Error reading file: {str(e)}")
```

---

## Key Files and Their Roles

| File | Purpose |
|------|---------|
| `config.yaml` | User configuration with environment variable substitution |
| `src/py_code_agent/cli/main.py` | CLI entry point, handles commands and chat mode |
| `src/py_code_agent/config/models.py` | Pydantic models for configuration with .env support |
| `src/py_code_agent/core/agent.py` | Main agent class, implements ReAct loop |
| `src/py_code_agent/core/session.py` | Conversation session management |
| `src/py_code_agent/tools/base.py` | Base tool classes and ToolResult definition |
| `src/py_code_agent/tools/builtin.py` | Built-in tools (read_file, write_file, execute_bash, task_done) |
| `src/py_code_agent/llm/litellm_provider.py` | LLM provider using LiteLLM |

---

## Summary

The data flow in Py Code Agent follows a clear pipeline:

1. **Configuration Loading**: Files are read, environment variables expanded, and Pydantic models validate the config
2. **Agent Initialization**: The agent is created with LLM provider, tools, and plugins
3. **Run Cycle**: The ReAct loop processes user input, streams LLM responses, and executes tools
4. **Tool Execution**: Tools validate inputs, perform operations, and return structured results
5. **Result Integration**: Results are added to session context and yielded as events for UI consumption

This architecture provides a clean separation of concerns with async support throughout the pipeline.
