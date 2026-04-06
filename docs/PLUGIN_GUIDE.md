# Py Code Agent 插件开发指导手册

本手册提供插件开发的实战指南，从零开始创建你的第一个插件。

## 概述

本手册将帮助你：
- 理解插件系统的工作原理
- 创建你的第一个插件
- 调试和解决问题
- 发布你的插件到 PyPI

---

## 第一章：快速开始

### 1.1 环境准备

确保已安装 Py Code Agent：

```bash
pip install py-code-agent
# 或
uvx py-code-agent --version
```

### 1.2 创建第一个插件

最简单的插件只需要实现 `register_tools` 方法：

```python
# my_first_plugin.py
from typing import List
from py_code_agent.plugins.hooks import hookimpl
from py_code_agent.tools.base import BaseTool, ToolDefinition, ToolResult

class HelloPlugin:
    @hookimpl
    def register_tools(self) -> List[BaseTool]:
        return [HelloTool()]

class HelloTool(BaseTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="hello",
            description="Say hello to the user",
            parameters=[]
        )
    
    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult.ok(
            data={"message": "Hello, World!"},
            summary="Said hello"
        )

Plugin = HelloPlugin
```

将文件放入 `.py-code-agent/plugins/` 目录，然后重启 Agent。

---

## 第二章：深入理解

### 2.1 插件生命周期

```
加载阶段 → 注册阶段 → 运行时 → 卸载阶段
    │           │           │
    ▼           ▼           ▼
 register_   register_    on_agent_
 tools()     tools()      start/end
```

### 2.2 Hook 调用顺序

```
Agent 启动
  │
  ├─► load_plugins() - 加载所有插件
  │
  ├─► register_tools() - 注册工具
  │
  ├─► get_system_prompt() - 聚合系统提示
  │
  ├─► on_agent_start(input) - Agent 开始
  │
  ├─► [工具执行循环]
  │     ├─► before_tool_execute()
  │     ├─► Tool.execute()
  │     └─► after_tool_execute()
  │
  └─► on_agent_end() - Agent 结束
```

---

## 第三章：工具开发详解

### 3.1 基础工具模板

```python
from py_code_agent.tools.base import (
    BaseTool,
    ToolDefinition,
    ToolParameter,
    ToolParameterType,
    ToolResult
)
from typing import Optional

class MyTool(BaseTool):
    """工具的简短描述"""
    
    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
    
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="my_tool",
            description="工具的详细描述",
            parameters=[
                ToolParameter(
                    name="input_text",
                    type=ToolParameterType.STRING,
                    description="输入文本的描述",
                    required=True
                ),
                ToolParameter(
                    name="count",
                    type=ToolParameterType.INTEGER,
                    description="可选参数",
                    required=False,
                    default=5
                ),
                ToolParameter(
                    name="enabled",
                    type=ToolParameterType.BOOLEAN,
                    description="开关选项",
                    required=False,
                    default=True
                )
            ]
        )
    
    async def execute(
        self,
        input_text: str,
        count: int = 5,
        enabled: bool = True,
        **kwargs
    ) -> ToolResult:
        # 检查参数
        if not input_text:
            return ToolResult.fail("input_text cannot be empty")
        
        if count < 1 or count > 100:
            return ToolResult.fail("count must be between 1 and 100")
        
        # 执行业务逻辑
        try:
            result = process_text(input_text, count, enabled)
            
            return ToolResult.ok(
                data={
                    "result": result,
                    "processed_count": len(result)
                },
                summary=f"处理了 {len(result)} 个项目"
            )
        except Exception as e:
            return ToolResult.fail(f"处理失败: {e}")

# 业务处理函数
def process_text(text: str, count: int, enabled: bool) -> list:
    if not enabled:
        return []
    return [text[i:i+count] for i in range(0, len(text), count)]
```

### 3.2 异步工具

工具默认异步执行，使用 `async/await`：

```python
import asyncio
import aiohttp

class AsyncTool(BaseTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="async_fetch",
            description="异步获取数据",
            parameters=[
                ToolParameter(
                    name="url",
                    type=ToolParameterType.STRING,
                    description="URL",
                    required=True
                )
            ]
        )
    
    async def execute(self, url: str, **kwargs) -> ToolResult:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    data = await response.json()
                    return ToolResult.ok(
                        data=data,
                        summary=f"获取成功: {response.status}"
                    )
        except Exception as e:
            return ToolResult.fail(f"请求失败: {e}")
```

### 3.3 带依赖的工具

工具可以持有其他组件的引用：

```python
class DatabaseTool(BaseTool):
    def __init__(self, db_connection):
        self.db = db_connection
    
    async def execute(self, query: str, **kwargs) -> ToolResult:
        try:
            result = self.db.execute(query)
            return ToolResult.ok(
                data={"rows": result},
                summary=f"返回 {len(result)} 行"
            )
        except Exception as e:
            return ToolResult.fail(f"数据库错误: {e}")

# 插件中注入依赖
class DBPlugin:
    def __init__(self):
        self.db = connect_database()
    
    def register_tools(self):
        return [DatabaseTool(self.db)]
```

---

## 第四章：高级特性

### 4.1 系统提示注入

```python
class MyPlugin:
    @hookimpl
    def get_system_prompt(self) -> str:
        return """## My Custom Plugin

This plugin provides specialized functionality:

- Use `my_tool` for specific tasks
- Tool accepts: text input, optional count parameter
- Returns structured data with results

Example:
```
user: process this text
agent: I'll use my_tool to process it
```"""
```

### 4.2 工具执行拦截

```python
class LoggingPlugin:
    @hookimpl
    def before_tool_execute(self, tool_name: str, arguments: Dict[str, Any]) -> None:
        print(f"[LOG] Executing {tool_name} with {arguments}")
    
    @hookimpl
    def after_tool_execute(
        self, tool_name: str, arguments: Dict[str, Any], result: Any
    ) -> None:
        print(f"[LOG] {tool_name} completed: {result.get('success')}")
```

### 4.3 错误增强

```python
class MyErrorPlugin:
    @hookimpl
    def enhance_tool_error(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        error_info: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        if tool_name == "my_tool":
            return {
                "error_type": "custom_error",
                "diagnosis": "自定义错误诊断",
                "fix_suggestions": [
                    "检查参数格式",
                    "确认输入有效"
                ],
                "confidence": 0.9
            }
        return None
    
    @hookimpl
    def enhance_tool_error_priority(self) -> int:
        return 50  # 较低优先级
```

### 4.4 心跳事件

```python
class HeartbeatPlugin:
    def __init__(self):
        self.pm = None  # 插件管理器引用
    
    def emit_event(self, event: str, data: Dict[str, Any]) -> None:
        if self.pm:
            self.pm.call_on_plugin_heartbeat(event, {
                "plugin_name": "my_plugin",
                "plugin_id": "my-001",
                "data": data
            })
    
    @hookimpl
    def on_agent_start(self, input: str) -> None:
        self.emit_event("started", {"input_length": len(input)})
```

### 4.5 动态配置

```python
class ConfigurablePlugin:
    def __init__(self):
        self._config = {}
    
    def configure(self, **kwargs) -> None:
        self._config = kwargs
    
    @hookimpl
    def register_tools(self) -> List[BaseTool]:
        return [ConfigurableTool(self._config)]
```

---

## 第五章：实战示例

### 5.1 文件处理插件

```python
import os
from pathlib import Path

class FilePlugin:
    @hookimpl
    def register_tools(self) -> List[BaseTool]:
        return [ReadFileTool(), WriteFileTool(), ListDirTool()]
    
    @hookimpl
    def get_system_prompt(self) -> str:
        return """## File Operations

Use file tools to read, write, and navigate the filesystem.
Always verify paths are within allowed directories."""


class ReadFileTool(BaseTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="read_file",
            description="Read content from a file",
            parameters=[
                ToolParameter(
                    name="path",
                    type=ToolParameterType.STRING,
                    description="File path to read",
                    required=True
                )
            ]
        )
    
    async def execute(self, path: str, **kwargs) -> ToolResult:
        try:
            file_path = Path(path).resolve()
            if not file_path.exists():
                return ToolResult.fail(f"File not found: {path}")
            
            content = file_path.read_text(encoding='utf-8')
            return ToolResult.ok(
                data={
                    "path": str(file_path),
                    "content": content,
                    "size": len(content)
                },
                summary=f"Read {len(content)} characters from {file_path.name}"
            )
        except Exception as e:
            return ToolResult.fail(f"Read error: {e}")


class WriteFileTool(BaseTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="write_file",
            description="Write content to a file",
            parameters=[
                ToolParameter(
                    name="path",
                    type=ToolParameterType.STRING,
                    description="File path to write",
                    required=True
                ),
                ToolParameter(
                    name="content",
                    type=ToolParameterType.STRING,
                    description="Content to write",
                    required=True
                )
            ]
        )
    
    async def execute(self, path: str, content: str, **kwargs) -> ToolResult:
        try:
            file_path = Path(path).resolve()
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding='utf-8')
            return ToolResult.ok(
                data={"path": str(file_path), "bytes_written": len(content)},
                summary=f"Wrote {len(content)} bytes to {file_path.name}"
            )
        except Exception as e:
            return ToolResult.fail(f"Write error: {e}")


class ListDirTool(BaseTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="list_dir",
            description="List directory contents",
            parameters=[
                ToolParameter(
                    name="path",
                    type=ToolParameterType.STRING,
                    description="Directory path",
                    required=False,
                    default="."
                )
            ]
        )
    
    async def self.execute(self, path: str = ".", **kwargs) -> ToolResult:
        try:
            dir_path = Path(path).resolve()
            if not dir_path.is_dir():
                return ToolResult.fail(f"Not a directory: {path}")
            
            items = []
            for item in dir_path.iterdir():
                items.append({
                    "name": item.name,
                    "type": "dir" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else None
                })
            
            return ToolResult.ok(
                data={"path": str(dir_path), "items": items},
                summary=f"Listed {len(items)} items in {dir_path.name}"
            )
        except Exception as e:
            return ToolResult.fail(f"List error: {e}")


Plugin = FilePlugin
```

### 5.2 HTTP API 插件

```python
import httpx
from typing import Optional

class HTTPPlugin:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)
    
    @hookimpl
    def register_tools(self) -> List[BaseTool]:
        return [HTTPTool(self.client)]
    
    @hookimpl
    def on_agent_end(self) -> None:
        # 清理资源
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            loop.create_task(self.client.aclose())
        except:
            pass


class HTTPTool(BaseTool):
    def __init__(self, client: httpx.AsyncClient):
        self.client = client
    
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="http_request",
            description="Make HTTP requests",
            parameters=[
                ToolParameter(
                    name="method",
                    type=ToolParameterType.STRING,
                    description="HTTP method",
                    required=False,
                    default="GET"
                ),
                ToolParameter(
                    name="url",
                    type=ToolParameterType.STRING,
                    description="Request URL",
                    required=True
                ),
                ToolParameter(
                    name="headers",
                    type=ToolParameterType.OBJECT,
                    description="Request headers",
                    required=False
                ),
                ToolParameter(
                    name="body",
                    type=ToolParameterType.OBJECT,
                    description="Request body (JSON)",
                    required=False
                )
            ]
        )
    
    async def execute(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[dict] = None,
        body: Optional[dict] = None,
        **kwargs
    ) -> ToolResult:
        try:
            response = await self.client.request(
                method=method.upper(),
                url=url,
                headers=headers,
                json=body
            )
            
            return ToolResult.ok(
                data={
                    "status": response.status_code,
                    "headers": dict(response.headers),
                    "body": response.text[:1000]  # 截断大响应
                },
                summary=f"HTTP {response.status_code}"
            )
        except Exception as e:
            return ToolResult.fail(f"Request failed: {e}")


Plugin = HTTPPlugin
```

---

## 第六章：调试与排错

### 6.1 常见问题

#### 问题 1: 插件不加载

**症状**: 工具未出现在工具列表中

**排查步骤**:
1. 检查文件位置是否正确
2. 检查 `Plugin` 变量是否正确导出
3. 检查是否有导入错误
4. 查看日志中的插件加载信息

```bash
pi-code-agent chat --debug
```

#### 问题 2: 工具执行失败

**症状**: 调用工具时返回错误

**排查步骤**:
1. 检查 execute 方法的返回类型
2. 确认参数类型匹配
3. 查看错误消息

```python
# 正确返回
return ToolResult.ok(data={...}, summary="...")

# 错误返回
return ToolResult.fail("错误消息")
```

#### 问题 3: Hook 不生效

**症状**: 实现了 hook 但未被调用

**检查**:
1. 方法名是否正确
2. 是否有 `@hookimpl` 装饰器
3. 方法签名是否正确

### 6.2 调试技巧

```python
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class DebugPlugin:
    @hookimpl
    def register_tools(self) -> List[BaseTool]:
        logger.debug("register_tools called")
        return [DebugTool()]
```

### 6.3 自愈机制日志

查看自愈修复记录：

```bash
# 启用详细日志
pi-code-agent chat --verbose 2>&1 | grep -i "repair\|heal"
```

---

## 第七章：打包与发布

### 7.1 本地测试

```bash
# 开发模式安装
cd /path/to/your-plugin
pip install -e .

# 验证安装
pi-code-agent plugin list
```

### 7.2 构建发布包

```bash
# 安装构建工具
pip install build twine

# 构建
python -m build

# 检查输出
ls dist/

# 上传到 Test PyPI（测试）
twine upload --repository-url https://test.pypi.org/legacy/ dist/*

# 上传到 PyPI（正式）
twine upload dist/*
```

### 7.3 版本号规范

遵循语义化版本：
- `0.1.0` - 初始开发版本
- `0.2.0` - 新功能
- `1.0.0` - 正式版本
- `1.0.1` - Bug 修复

---

## 第八章：最佳实践

### 8.1 代码质量

```python
# ✅ 正确：完整类型注解
async def execute(self, query: str, limit: int = 10, **kwargs) -> ToolResult:

# ❌ 错误：使用 any
async def execute(self, query, limit=10, **kwargs) -> ToolResult:

# ❌ 错误：空 catch
try:
    ...
except:
    pass
```

### 8.2 错误处理

```python
async def execute(self, arg: str, **kwargs) -> ToolResult:
    try:
        result = do_work(arg)
        return ToolResult.ok(data=result, summary="成功")
    except ValueError as e:
        return ToolResult.fail(f"参数错误: {e}")
    except TimeoutError:
        return ToolResult.fail("操作超时")
    except Exception as e:
        return ToolResult.fail(f"未知错误: {e}")
```

### 8.3 资源清理

```python
class MyPlugin:
    @hookimpl
    def on_agent_end(self) -> None:
        # 清理所有资源
        if hasattr(self, 'client'):
            asyncio.create_task(self.client.aclose())
```

### 8.4 配置管理

```python
class MyPlugin:
    def configure(self, **config) -> None:
        self.config = config
    
    def _get_config(self, key: str, default=None):
        # 支持环境变量替换
        value = self.config.get(key, default)
        if isinstance(value, str) and value.startswith("${"):
            import re
            env_var = re.match(r'\$\{([^}]+)\}', value).group(1)
            value = os.environ.get(env_var, default)
        return value
```

---

## 附录

### A. 类型参考

```python
from py_code_agent.tools.base import (
    ToolParameterType,
    ToolResult,
    ToolDefinition,
    ToolParameter
)

# 可用类型
ToolParameterType.STRING    # "str"
ToolParameterType.INTEGER   # 1
ToolParameterType.NUMBER    # 1.5
ToolParameterType.BOOLEAN    # true/false
ToolParameterType.ARRAY      # []
ToolParameterType.OBJECT     # {}
```

### B. 配置参考

```yaml
# config.yaml
plugins:
  enabled:
    - file:my_plugin
    - my_other_plugin
  disabled:
    - file:unwanted

my_plugin:
  option1: value1
  option2: value2
```

### C. 依赖参考

```toml
[project]
dependencies = [
    "httpx>=0.27.0",
    "aiohttp>=3.9.0",
    "pydantic>=2.0.0",
]
```

---

## 相关文档

- [PLUGIN_SPEC.md](./PLUGIN_SPEC.md) - 插件规范参考
- [ARCHITECTURE.md](./ARCHITECTURE.md) - 系统架构
- [配置文档](./CONFIG.md) - 配置说明