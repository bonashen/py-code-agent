# Py Code Agent 插件开发规范

本文档定义了 Py Code Agent 插件系统的开发规范，适用于创建第三方独立插件包。

## 目录

1. [插件系统架构](#插件系统架构)
2. [插件结构](#插件结构)
3. [Hook 规范](#hook-规范)
4. [工具开发](#工具开发)
5. [Entry Points 注册](#entry-points-注册)
6. [包配置](#包配置)
7. [最佳实践](#最佳实践)
8. [示例插件](#示例插件)

---

## 插件系统架构

Py Code Agent 使用 `pluggy` 库实现插件系统，支持 5 层自愈机制。

### 插件层级

| 层级 | 目录 | 用途 |
|------|------|------|
| Built-in | `<repo>/plugins/builtin/` | 随包分发 |
| Local | `./.py-code-agent/plugins/` | 项目级 |
| Global | `~/.config/py-code-agent/plugins/` | 用户级 |
| PyPI Entry Points | 已安装的包 | 社区插件 |

### 自愈机制

| 层级 | 场景 | 修复方式 |
|------|------|----------|
| 1 | Hook 方法崩溃 | 运行时 try/except 包装 |
| 2 | 插件缺少 hook 方法 | 注入空实现 |
| 3 | 导入错误（缺包） | pip install 后重试 |
| 4 | 属性错误 | 注入缺失属性 |
| 5 | Tool execute() 崩溃 | AST 补丁修复并重载 |

---

## 插件结构

### 目录结构

```
py-code-agent-my-plugin/
├── pyproject.toml
├── README.md
└── py_code_agent_my_plugin/
    └── plugin.py
```

### 最小插件类

```python
from typing import List
from py_code_agent.plugins.hooks import hookimpl
from py_code_agent.tools.base import BaseTool

class MyPlugin:
    @hookimpl
    def register_tools(self) -> List[BaseTool]:
        """注册插件提供的工具"""
        return []

Plugin = MyPlugin  # 必须导出 Plugin 作为入口点
```

---

## Hook 规范

### ToolHooks

#### register_tools()

```python
@hookimpl
def register_tools(self) -> List[BaseTool]:
    """返回插件提供的工具列表"""
    return [MyTool()]
```

#### before_tool_execute(tool_name, arguments)

```python
@hookimpl
def before_tool_execute(self, tool_name: str, arguments: Dict[str, Any]) -> None:
    """工具执行前调用"""
    pass
```

#### after_tool_execute(tool_name, arguments, result)

```python
@hookimpl
def after_tool_execute(
    self, tool_name: str, arguments: Dict[str, Any], result: Any
) -> None:
    """工具执行后调用，result 是原始工具数据字典"""
    pass
```

#### enhance_tool_error(tool_name, arguments, error_info)

```python
@hookimpl
def enhance_tool_error(
    self,
    tool_name: str,
    arguments: Dict[str, Any],
    error_info: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """工具执行失败时调用，返回增强的错误信息"""
    # error_info 结构:
    # {
    #     "error_type": "missing_dependency" | "wrong_tool" | "permission_denied"
    #                 | "invalid_arguments" | "execution_error" | "unknown",
    #     "error": "原始错误消息",
    #     "diagnosis": "人类可读的错误分析",
    #     "suggestions": ["修复建议列表"]
    # }
    return {
        "error_type": "...",
        "diagnosis": "...",
        "fix_suggestions": ["..."],
        "confidence": 0.8
    }
```

#### enhance_tool_error_priority()

```python
@hookimpl
def enhance_tool_error_priority(self) -> int:
    """返回 enhance_tool_error 优先级，数字越小越高"""
    return 100  # 默认优先级
```

### AgentHooks

#### on_agent_start(input)

```python
@hookimpl
def on_agent_start(self, input: str) -> None:
    """Agent 开始处理输入时调用"""
    pass
```

#### on_agent_end()

```python
@hookimpl
def on_agent_end(self) -> None:
    """Agent 完成处理时调用"""
    pass
```

#### on_llm_call(messages, tools)

```python
@hookimpl
def on_llm_call(
    self, messages: List[Dict[str, str]], tools: List[Dict[str, Any]]
) -> None:
    """每次 LLM API 调用前调用"""
    pass
```

#### on_llm_response(response)

```python
@hookimpl
def on_llm_response(self, response: Any) -> None:
    """每次 LLM API 响应后调用（流式块）"""
    pass
```

#### get_system_prompt()

```python
@hookimpl
def get_system_prompt(self) -> str:
    """返回注入到系统提示的额外内容"""
    return """## My Plugin
    
    使用 my_tool 执行特定任务。"""
```

#### on_plugin_heartbeat(event, data)

```python
@hookimpl
def on_plugin_heartbeat(
    self,
    event: str,
    data: Dict[str, Any],
) -> None:
    """插件发出心跳事件时调用
    
    统一事件格式:
    {
        "event_type": "plugin_heartbeat",
        "event": "specific_event",
        "plugin_name": "plugin_name",
        "plugin_id": "plugin_001",
        "data": {...}
    }
    
    通用事件:
    - "loaded": 插件加载成功
    - "updated": 插件配置更新
    - "started": 操作开始
    - "completed": 操作完成
    - "failed": 操作失败
    - "retry": 操作重试
    """
    pass
```

#### get_capabilities()

```python
@hookimpl
def get_capabilities(self) -> Dict[str, Any]:
    """返回插件能力，供 LLM 了解插件提供什么"""
    return {
        "name": "my_plugin",
        "description": "我的插件描述",
        "tools": ["tool1", "tool2"],
        "keywords": ["keyword1", "keyword2"]
    }
```

---

## 工具开发

### BaseTool 子类

```python
from py_code_agent.tools.base import (
    BaseTool,
    ToolDefinition,
    ToolParameter,
    ToolParameterType,
    ToolResult
)

class MyTool(BaseTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="my_tool",
            description="工具描述",
            parameters=[
                ToolParameter(
                    name="arg1",
                    type=ToolParameterType.STRING,
                    description="参数描述",
                    required=True
                ),
                ToolParameter(
                    name="optional_arg",
                    type=ToolParameterType.INTEGER,
                    description="可选参数",
                    required=False,
                    default=10
                )
            ]
        )

    async def execute(self, arg1: str, optional_arg: int = 10, **kwargs) -> ToolResult:
        # 实现逻辑
        try:
            result = do_something(arg1)
            return ToolResult.ok(
                data={"key": "value"},
                summary="成功描述"
            )
        except Exception as e:
            return ToolResult.fail(f"错误: {e}")
```

### ToolParameterType 枚举

```python
from py_code_agent.tools.base import ToolParameterType

# 可用类型:
ToolParameterType.STRING    # 字符串
ToolParameterType.INTEGER   # 整数
ToolParameterType.NUMBER    # 浮点数
ToolParameterType.BOOLEAN    # 布尔值
ToolParameterType.ARRAY     # 数组
ToolParameterType.OBJECT     # 对象
```

### ToolResult

```python
from py_code_agent.tools.base import ToolResult

# 成功结果
return ToolResult.ok(
    data={"key": "value"},      # 任意可序列化数据
    summary="简要描述"           # 用于展示的摘要
)

# 失败结果
return ToolResult.fail("错误消息")
# 或
return ToolResult(
    success=False,
    data={},
    error="错误消息",
    summary="失败描述"
)
```

---

## Entry Points 注册

### pyproject.toml 配置

```toml
[project]
name = "py-code-agent-my-plugin"
version = "0.1.0"

[project.entry-points."py_code_agent.plugins"]
my_plugin = "py_code_agent_my_plugin.plugin:Plugin"
```

**关键点**:
- Entry point 组名必须是 `py_code_agent.plugins`
- 格式: `模块路径:类名`
- 入口点类必须导出为 `Plugin`

---

## 包配置

### pyproject.toml 完整示例

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "py-code-agent-my-plugin"
version = "0.1.0"
description = "我的插件描述"
readme = "README.md"
requires-python = ">=3.9"
license = {text = "MIT"}
authors = [
    {name = "Author Name", email = "email@example.com"}
]
keywords = ["py-code-agent", "plugin"]
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3.9",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
]

dependencies = [
    "httpx>=0.27.0",
]

[project.optional-dependencies]
all = [
    "httpx>=0.27.0",
]

[project.entry-points."py_code_agent.plugins"]
my_plugin = "py_code_agent_my_plugin.plugin:Plugin"

[tool.hatch.build.targets.wheel]
packages = ["py_code_agent_my_plugin"]
```

---

## 最佳实践

### 1. 错误处理

```python
# 始终在 execute 中捕获异常
async def execute(self, arg: str, **kwargs) -> ToolResult:
    try:
        result = do_work(arg)
        return ToolResult.ok(data=result, summary="成功")
    except ValueError as e:
        return ToolResult.fail(f"参数错误: {e}")
    except Exception as e:
        return ToolResult.fail(f"执行错误: {e}")
```

### 2. 类型注解

```python
# 必须使用完整类型注解，禁止 as any
async def execute(
    self,
    query: str,
    limit: int = 10,
    **kwargs
) -> ToolResult:
    # ...
```

### 3. 依赖声明

```python
# 在 pyproject.toml 中声明所有依赖
dependencies = [
    "httpx>=0.27.0",
    "pydantic>=2.0.0",
]
```

### 4. 配置支持

```python
# 支持环境变量 substitution
def configure(self, token: Optional[str] = None) -> None:
    if token:
        token = os.environ.get(token.replace("${", "").replace("}", ""), "")
    # ...
```

### 5. 依赖声明

```python
# 在 docstring 中声明依赖
class MyPlugin:
    """My plugin description.
    
    Dependencies:
        - (file:gateway) for MCP Gateway plugin integration
    """
```

---

## 示例插件

### 完整示例: py-code-agent-git

```
py-code-agent-git/
├── pyproject.toml
├── README.md
└── py_code_agent_git/
    └── plugin.py
```

**plugin.py**:

```python
import subprocess
from pathlib import Path
from typing import List

from py_code_agent.plugins.hooks import hookimpl
from py_code_agent.tools.base import BaseTool, ToolDefinition, ToolResult


class GitStatusPlugin:
    @hookimpl
    def register_tools(self) -> List[BaseTool]:
        return [GitStatusTool()]

    @hookimpl
    def get_system_prompt(self) -> str:
        return """## Git Integration

Use git tools to understand the repository context before making changes.

- `git_status`: Get current branch, recent commits, and working tree status — always run this before planning major changes."""


class GitStatusTool(BaseTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="git_status",
            description="Get git status, branch, and recent commits of the current repository",
            parameters=[],
        )

    async def execute(self, **kwargs) -> ToolResult:
        try:
            cwd = Path.cwd()
            status = subprocess.run(
                ["git", "status", "--short"], cwd=cwd, capture_output=True, text=True, timeout=5
            )
            branch = subprocess.run(
                ["git", "branch", "--show-current"], cwd=cwd, capture_output=True, text=True, timeout=5
            )
            log = subprocess.run(
                ["git", "log", "--oneline", "-5"], cwd=cwd, capture_output=True, text=True, timeout=5
            )

            result = f"Branch: {branch.stdout.strip() or '(detached)'}\n\n"
            result += f"Recent commits:\n{log.stdout.strip() or 'No commits'}\n\n"
            result += f"Status: {status.stdout.strip() or 'Not a git repository'}"

            return ToolResult.ok(
                data={"output": result},
                summary=f"Git status for {cwd.name}",
            )
        except FileNotFoundError:
            return ToolResult.fail("git not found - is git installed?")
        except subprocess.TimeoutExpired:
            return ToolResult.fail("git command timed out")
        except Exception as e:
            return ToolResult.fail(f"git error: {e}")


Plugin = GitStatusPlugin
```

**pyproject.toml**:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "py-code-agent-git"
version = "0.1.0"
description = "Git plugin for Py Code Agent"
requires-python = ">=3.9"
license = {text = "MIT"}

[project.entry-points."py_code_agent.plugins"]
git = "py_code_agent_git.plugin:Plugin"

[tool.hatch.build.targets.wheel]
packages = ["py_code_agent_git"]
```

---

## 编译打包

```bash
# 安装 build 工具
pip install build

# 编译 wheel
python -m build --wheel /path/to/py-code-agent-my-plugin

# 编译 sdist
python -m build --sdist /path/to/py-code-agent-my-plugin
```

输出位于 `dist/` 目录:
- `*.whl` - wheel 包
- `*.tar.gz` - 源码分发

---

## 安装使用

```bash
# 安装
pip install py-code-agent-my-plugin

# 或从本地 wheel 安装
pip install dist/py_code_agent_my_plugin-0.1.0-py3-none-any.whl
```

在 `config.yaml` 中启用:

```yaml
plugins:
  enabled:
    - my_plugin
```