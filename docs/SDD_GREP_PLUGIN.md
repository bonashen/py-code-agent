# GrepPlugin — Software Design Document (SDD)

**版本**: 2.0.0  
**日期**: 2026-04-02  
**状态**: 草案  
**类型**: 第三方插件 (PyPI Entry Point)  
**变更**: 融合 AST 搜索能力，从单引擎升级为双引擎架构

---

## 目录

1. [概述](#1-概述)
2. [需求分析](#2-需求分析)
3. [架构设计](#3-架构设计)
4. [双引擎设计](#4-双引擎设计)
5. [工具设计](#5-工具设计)
6. [Hook 集成](#6-hook-集成)
7. [数据结构](#7-数据结构)
8. [包结构](#8-包结构)
9. [错误处理](#9-错误处理)
10. [测试策略](#10-测试策略)
11. [发布计划](#11-发布计划)
12. [附录](#12-附录)

---

## 1. 概述

### 1.1 目的

GrepPlugin 为 Py Code Agent 提供 **统一的代码搜索能力**，融合文本级正则搜索与 AST 结构搜索，使 Agent 能够通过单一工具接口完成从简单关键字匹配到复杂语法模式搜索的全场景需求。

### 1.2 范围

| 在范围内 | 不在范围内 |
|----------|------------|
| 正则表达式搜索（文本级） | 跨仓库搜索 |
| AST 模式匹配（语法级） | 索引构建/维护 |
| 关键字/文本搜索 | 数据库/二进制文件搜索 |
| 文件模式过滤（glob） | 独立替换工具（由 `ast_grep_replace` 覆盖） |
| 搜索结果上下文行 | |
| 多文件批量搜索 | |

### 1.3 定位

GrepPlugin 作为 **第三方独立插件包** (`py-code-agent-grep`)，通过 PyPI Entry Point 注册到 Py Code Agent 的插件系统。

**核心价值**: 一个工具覆盖 Agent 的所有搜索需求，无需在多个工具间切换。

```
用户请求 "find all console.log calls"
         → Agent 调用 grep_search (自动选择引擎)
         → 检测到代码结构模式 → 使用 AST 引擎
         → 返回匹配文件和行号
```

### 1.4 与现有工具的关系

| 工具 | 来源 | 能力 | GrepPlugin 定位 |
|------|------|------|-----------------|
| `grep_search` (GrepPlugin) | 本插件 | 文本级 + AST 级统一搜索 | **统一入口** |
| `ast_grep_replace` (opencode) | 内置 | AST 替换/重写 | GrepPlugin 不覆盖替换能力 |
| `grep` (shell) | bash 工具 | 需要手动构建命令 | GrepPlugin 提供结构化搜索 |
| `find` (shell) | bash 工具 | 文件名搜索 | GrepPlugin 提供内容搜索 |

---

## 2. 需求分析

### 2.1 功能需求

| ID | 需求 | 优先级 | 引擎 |
|----|------|--------|------|
| F1 | 支持正则表达式搜索代码内容 | P0 | TextEngine |
| F2 | 支持简单关键字搜索（非正则） | P0 | TextEngine |
| F3 | 支持 AST 模式匹配（元变量 `$VAR`, `$$$`） | P0 | AstEngine |
| F4 | 支持语言自动检测 | P0 | AstEngine |
| F5 | 支持 glob 文件模式过滤 | P0 | 共享 |
| F6 | 支持匹配结果上下文行 | P1 | 共享 |
| F7 | 支持大小写敏感/不敏感切换 | P1 | TextEngine |
| F8 | 支持排除目录 | P0 | 共享 |
| F9 | 支持搜索结果限制 | P1 | 共享 |
| F10 | 支持搜索超时控制 | P1 | 共享 |
| F11 | 自动引擎选择（根据 pattern 特征） | P0 | 共享 |

### 2.2 非功能需求

| ID | 需求 | 指标 |
|----|------|------|
| NF1 | 文本搜索性能 | 1000 文件 < 2 秒 |
| NF2 | AST 搜索性能 | 1000 文件 < 5 秒 |
| NF3 | 内存安全 | 不加载整个文件到内存（TextEngine 逐行扫描） |
| NF4 | 路径安全 | 仅搜索工作目录内文件 |
| NF5 | 编码兼容 | UTF-8 优先，非 UTF-8 文件跳过 |
| NF6 | 依赖最小化 | 仅依赖 `ast-grep-py`（PyO3 原生绑定） |

### 2.3 用户场景

**场景 1: 查找函数调用（AST 引擎）**
```
用户: "find all places where `asyncio.gather` is called"
Agent: grep_search(pattern="asyncio.gather($$$)", lang="python")
→ AST 引擎匹配所有调用形式（换行/空格差异不影响）
```

**场景 2: 查找 TODO 注释（文本引擎）**
```
用户: "find all TODO comments in the codebase"
Agent: grep_search(pattern="TODO|FIXME|HACK", include="*.{py,ts,js,go}")
→ 文本引擎搜索（AST 无法匹配注释）
```

**场景 3: 查找特定参数模式的调用（AST 引擎）**
```
用户: "find all fetch calls with POST method"
Agent: grep_search(pattern='fetch($URL, {method: "POST", $$$})', lang="typescript")
→ AST 引擎精确匹配参数结构
```

**场景 4: 自动引擎选择**
```
用户: "find all console.log calls"
Agent: grep_search(pattern="console.log($$$)")
→ 检测到元变量 ($$$) → 自动切换到 AST 引擎
```

---

## 3. 架构设计

### 3.1 包结构

```
py-code-agent-grep/
├── pyproject.toml
├── README.md
├── LICENSE
└── py_code_agent_grep/
    ├── __init__.py
    ├── plugin.py          # GrepPlugin 类 + Entry Point
    ├── tools.py           # GrepSearchTool, GrepCountTool
    ├── engine.py          # 搜索引擎核心（双引擎 + 路由）
    ├── text_engine.py     # 文本搜索引擎（逐行扫描）
    ├── ast_engine.py      # AST 搜索引擎（ast-grep-py）
    ├── file_scanner.py    # 文件发现 + 过滤
    └── types.py           # 数据类型定义
```

### 3.2 组件关系

```
┌─────────────────────────────────────────────────────────┐
│                        GrepPlugin                        │
│                                                          │
│  ┌──────────────┐  ┌──────────────────────────────────┐  │
│  │ GrepSearchTool│  │        GrepCountTool             │  │
│  └──────┬───────┘  └────────────┬─────────────────────┘  │
│         │                       │                         │
│         └───────────┬───────────┘                         │
│                     ▼                                      │
│         ┌───────────────────────┐                          │
│         │     SearchEngine      │                          │
│         │   (统一搜索接口)       │                          │
│         └───────────┬───────────┘                          │
│                     │                                      │
│         ┌───────────┴───────────┐                          │
│         │    EngineRouter       │                          │
│         │  (自动引擎选择)        │                          │
│         └──────┬───────┬───────┘                          │
│                │       │                                   │
│     ┌──────────┴──┐ ┌─┴──────────┐                        │
│     │ TextEngine  │ │ AstEngine  │                        │
│     │ (正则/文本)  │ │ (AST 模式)  │                        │
│     └──────┬──────┘ └──┬─────────┘                        │
│            │           │                                    │
│     ┌──────┴───────────┴──────┐                            │
│     │      FileScanner        │                            │
│     │   (文件发现 + 过滤)      │                            │
│     └─────────────────────────┘                            │
└──────────────────────────────────────────────────────────┘
```

### 3.3 引擎路由逻辑

```
SearchEngine.search(pattern, ...)
    │
    ├── EngineRouter.select(pattern, lang)
    │     │
    │     ├── 包含元变量 ($VAR, $$$)? → AstEngine
    │     ├── 指定了 lang 参数? → AstEngine
    │     ├── 搜索目标是注释/字符串/TODO? → TextEngine
    │     ├── 非代码文件 (.md, .json, .yaml)? → TextEngine
    │     └── 默认 → TextEngine (更快)
    │
    └── 执行选中的引擎
```

### 3.4 与 PluginManager 的集成

```python
class GrepPlugin:
    @hookimpl
    def register_tools(self) -> List[BaseTool]:
        return [GrepSearchTool(), GrepCountTool()]
    
    @hookimpl
    def get_system_prompt(self) -> str:
        return """## Code Search (Grep)

Use `grep_search` as your unified search tool:
- **Text mode**: regex patterns for comments, strings, TODOs, keywords
  Example: `grep_search(pattern="TODO|FIXME")`
- **AST mode**: structural patterns with meta-variables ($VAR, $$$)
  Example: `grep_search(pattern="def $FUNC($$$):", lang="python")`
- **Auto-detect**: The engine is automatically selected based on your pattern.
  Use `$$$` or specify `lang` to trigger AST search.

Use `grep_count` for quick existence checks before full search.

Default excludes: .git, node_modules, .venv, __pycache__, dist, build
"""
```

---

## 4. 双引擎设计

### 4.1 TextEngine — 文本搜索引擎

与 v1.0 保持一致：纯标准库实现，逐行扫描，正则表达式匹配。

**核心特性**:
- 零外部依赖
- 逐行扫描（内存安全）
- 支持正则表达式 + 简单关键字
- 支持上下文行捕获
- 支持大小写敏感切换

### 4.2 AstEngine — AST 搜索引擎

基于 `ast-grep-py` (v0.42.0) 的 PyO3 原生绑定。

**安装**: `pip install ast-grep-py`

**核心特性**:
- 25 种编程语言支持
- AST 模式匹配（元变量 `$VAR`, `$$$`）
- 语言自动检测（fallback 到文件扩展名）
- 精确语法匹配（忽略空格/换行差异）
- 支持 AST 节点上下文

**支持的 25 种语言**:

| 语言 | 扩展名 | 语言 | 扩展名 |
|------|--------|------|--------|
| TypeScript | `.ts`, `.tsx` | Scala | `.scala` |
| JavaScript | `.js`, `.jsx` | Swift | `.swift` |
| Python | `.py` | Solidity | `.sol` |
| Java | `.java` | Nix | `.nix` |
| Go | `.go` | Lua | `.lua` |
| Rust | `.rs` | Kotlin | `.kt` |
| C | `.c`, `.h` | PHP | `.php` |
| C++ | `.cpp`, `.hpp` | HTML | `.html` |
| C# | `.cs` | CSS | `.css` |
| Ruby | `.rb` | YAML | `.yaml`, `.yml` |
| Haskell | `.hs` | JSON | `.json` |
| Elixir | `.ex`, `.exs` | Bash | `.sh`, `.bash` |

### 4.3 AstEngine 实现设计

```python
"""AST search engine powered by ast-grep-py (PyO3 binding)."""

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ast_grep_py import SgRoot  # PyO3 native binding

from py_code_agent_grep.types import AstMatch, SearchConfig
from py_code_agent_grep.file_scanner import FileScanner


# Language extension mapping
LANG_EXTENSIONS: Dict[str, List[str]] = {
    "typescript": [".ts", ".tsx"],
    "javascript": [".js", ".jsx", ".mjs", ".cjs"],
    "python": [".py"],
    "java": [".java"],
    "go": [".go"],
    "rust": [".rs"],
    "c": [".c", ".h"],
    "cpp": [".cpp", ".hpp", ".cc", ".cxx"],
    "csharp": [".cs"],
    "ruby": [".rb"],
    "scala": [".scala"],
    "swift": [".swift"],
    "kotlin": [".kt", ".kts"],
    "php": [".php"],
    "html": [".html", ".htm"],
    "css": [".css", ".scss", ".less"],
    "yaml": [".yaml", ".yml"],
    "json": [".json"],
    "bash": [".sh", ".bash"],
    "lua": [".lua"],
    "elixir": [".ex", ".exs"],
    "haskell": [".hs"],
    "nix": [".nix"],
    "solidity": [".sol"],
}

# Reverse mapping: extension → language
EXT_TO_LANG: Dict[str, str] = {}
for lang, exts in LANG_EXTENSIONS.items():
    for ext in exts:
        EXT_TO_LANG[ext] = lang


class AstEngine:
    """AST-based search engine using ast-grep-py (PyO3 binding)."""

    @staticmethod
    def search(
        pattern: str,
        search_dir: str = ".",
        lang: Optional[str] = None,
        include: str = "*",
        exclude_dirs: Optional[List[str]] = None,
        context_before: int = 0,
        context_after: int = 0,
        max_results: int = 100,
    ) -> "SearchResult":
        """Search using AST pattern matching."""
        from py_code_agent_grep.types import Match, SearchResult

        matches: List[Match] = []
        files_searched = 0
        files_matched_set: set[str] = set()
        total_matches = 0

        for fpath in FileScanner.discover(search_dir, include, exclude_dirs):
            # Determine language for this file
            file_lang = lang or _detect_language(fpath)
            if file_lang is None:
                continue  # Skip unsupported file types

            files_searched += 1
            file_matches = _search_file_ast(
                fpath, pattern, file_lang, context_before, context_after
            )
            if file_matches:
                files_matched_set.add(str(fpath))
                for m in file_matches:
                    total_matches += 1
                    if len(matches) < max_results:
                        matches.append(m)

        return SearchResult(
            pattern=pattern,
            search_dir=str(Path(search_dir).resolve()),
            total_matches=total_matches,
            files_searched=files_searched,
            files_matched=len(files_matched_set),
            matches=matches,
            truncated=total_matches > max_results,
            engine="ast",  # 标记使用的引擎
        )

    @staticmethod
    def count(
        pattern: str,
        search_dir: str = ".",
        lang: Optional[str] = None,
        include: str = "*",
        exclude_dirs: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Quick AST match count without collecting content."""
        total = 0
        files_searched = 0
        per_file: Dict[str, int] = {}

        for fpath in FileScanner.discover(search_dir, include, exclude_dirs):
            file_lang = lang or _detect_language(fpath)
            if file_lang is None:
                continue

            files_searched += 1
            count = _count_file_ast(fpath, pattern, file_lang)
            if count > 0:
                total += count
                per_file[str(fpath)] = count

        return {
            "total_matches": total,
            "files_searched": files_searched,
            "files_matched": len(per_file),
            "per_file": per_file,
            "engine": "ast",
        }


def _search_file_ast(
    fpath: Path,
    pattern: str,
    lang: str,
    ctx_before: int,
    ctx_after: int,
) -> List[Match]:
    """Search a single file using AST pattern matching."""
    try:
        content = fpath.read_text(encoding="utf-8", errors="replace")
        sg = SgRoot(content, lang)
        root = sg.root()
        matches_node = root.find(pattern)
    except Exception:
        return []

    matches = []
    if matches_node is None:
        return matches

    # Collect all matches
    all_nodes = list(root.find_all(pattern))
    lines = content.split("\n")

    for node in all_nodes:
        start_line = node.start_pos()["line"]  # 0-based
        end_line = node.end_pos()["line"]
        matched_text = node.text()

        before = lines[max(0, start_line - ctx_before):start_line]
        after = lines[end_line + 1:end_line + 1 + ctx_after]

        matches.append(Match(
            file=str(fpath),
            line=start_line + 1,  # 1-based
            content=matched_text,
            context_before=before,
            context_after=after,
        ))

    return matches


def _count_file_ast(fpath: Path, pattern: str, lang: str) -> int:
    """Count AST matches in a single file."""
    try:
        content = fpath.read_text(encoding="utf-8", errors="replace")
        sg = SgRoot(content, lang)
        root = sg.root()
        return len(list(root.find_all(pattern)))
    except Exception:
        return 0


def _detect_language(fpath: Path) -> Optional[str]:
    """Detect programming language from file extension."""
    ext = fpath.suffix.lower()
    return EXT_TO_LANG.get(ext)
```

### 4.4 EngineRouter — 自动引擎选择

```python
import re
from typing import Optional


class EngineRouter:
    """Automatically selects the best search engine based on pattern analysis."""

    # Meta-variable patterns that indicate AST search is needed
    AST_META_PATTERN = re.compile(r'\$[A-Z_][A-Z_0-9]*|\$\$\$')

    # Patterns that are better suited for text search
    TEXT_HINTS = [
        r'TODO|FIXME|HACK|XXX',      # Comments
        r'#.*|//.*|/\*.*',           # Comment markers
        r'["\'].*["\']',             # String literals
    ]

    @classmethod
    def select(
        cls,
        pattern: str,
        lang: Optional[str] = None,
        include: str = "*",
    ) -> str:
        """Return 'ast' or 'text' based on pattern analysis.
        
        Decision logic (evaluated in order):
        1. Contains meta-variables ($VAR, $$$) → AST
        2. Explicit lang specified → AST
        3. Include pattern targets non-code files → TEXT
        4. Pattern matches comment/string hints → TEXT
        5. Default → TEXT (faster, more universal)
        """
        # Rule 1: Meta-variables → AST
        if cls.AST_META_PATTERN.search(pattern):
            return "ast"

        # Rule 2: Explicit language → AST
        if lang is not None:
            return "ast"

        # Rule 3: Non-code file patterns → TEXT
        non_code_patterns = ["*.md", "*.txt", "*.log", "*.csv", "*.xml"]
        for nc_pattern in non_code_patterns:
            if include == nc_pattern or nc_pattern in include:
                return "text"

        # Rule 4: Comment/string hints → TEXT
        for hint in cls.TEXT_HINTS:
            if re.search(hint, pattern, re.IGNORECASE):
                return "text"

        # Rule 5: Default → TEXT
        return "text"
```

---

## 5. 工具设计

### 5.1 GrepSearchTool

**统一搜索工具**，自动选择文本引擎或 AST 引擎。

#### ToolDefinition

```python
ToolDefinition(
    name="grep_search",
    description=(
        "Unified code search — supports both regex text search and AST structural search. "
        "The engine is automatically selected based on your pattern:\n"
        "- **Text mode**: Use regex patterns for comments, strings, keywords. "
          "Example: pattern='TODO|FIXME'\n"
        "- **AST mode**: Use meta-variables ($VAR, $$$) for structural matching. "
          "Example: pattern='def $FUNC($$$):'\n"
        "You can also force AST mode by specifying the `lang` parameter."
    ),
    parameters=[
        ToolParameter(
            name="pattern",
            type=ToolParameterType.STRING,
            description=(
                "Search pattern. Supports two modes:\n"
                "- Text mode (default): Standard regex, e.g., 'def test_', 'TODO|FIXME'\n"
                "- AST mode: Structural patterns with meta-variables, e.g., 'def $FUNC($$$):'\n"
                "Meta-variables: $VAR matches a single AST node, $$$ matches zero or more nodes."
            ),
            required=True,
        ),
        ToolParameter(
            name="lang",
            type=ToolParameterType.STRING,
            description=(
                "Programming language for AST search. "
                "When specified, forces AST engine. "
                "Supported: python, typescript, javascript, java, go, rust, c, cpp, csharp, "
                "ruby, scala, swift, kotlin, php, html, css, yaml, json, bash, lua, elixir, "
                "haskell, nix, solidity. "
                "If omitted, engine is auto-selected based on pattern."
            ),
            required=False,
        ),
        ToolParameter(
            name="search_dir",
            type=ToolParameterType.STRING,
            description="Directory to search. Default: '.'",
            required=False,
            default=".",
        ),
        ToolParameter(
            name="include",
            type=ToolParameterType.STRING,
            description="Glob pattern to filter files. Default: '*'",
            required=False,
            default="*",
        ),
        ToolParameter(
            name="exclude_dirs",
            type=ToolParameterType.ARRAY,
            description=(
                "Directories to exclude. "
                "Default: ['.git', 'node_modules', '.venv', '__pycache__', 'dist', 'build']"
            ),
            required=False,
        ),
        ToolParameter(
            name="case_sensitive",
            type=ToolParameterType.BOOLEAN,
            description="Case sensitive search (text mode only). Default: False.",
            required=False,
            default=False,
        ),
        ToolParameter(
            name="context_before",
            type=ToolParameterType.INTEGER,
            description="Lines before each match. Default: 0.",
            required=False,
            default=0,
        ),
        ToolParameter(
            name="context_after",
            type=ToolParameterType.INTEGER,
            description="Lines after each match. Default: 0.",
            required=False,
            default=0,
        ),
        ToolParameter(
            name="max_results",
            type=ToolParameterType.INTEGER,
            description="Max matches to return. Default: 100.",
            required=False,
            default=100,
        ),
    ],
)
```

#### 返回格式

```json
{
  "success": true,
  "data": {
    "pattern": "def $FUNC($$$):",
    "search_dir": "/path/to/project",
    "engine": "ast",
    "total_matches": 42,
    "files_searched": 150,
    "files_matched": 8,
    "matches": [
      {
        "file": "src/core/agent.py",
        "line": 23,
        "content": "def run(self, task: str):",
        "context_before": ["class Agent:"],
        "context_after": [
            "    \"\"\"Execute the task.\"\"\"",
            "    pass"
        ]
      }
    ]
  },
  "summary": "Found 42 matches across 8 files (ast engine, 150 files searched)"
}
```

### 5.2 GrepCountTool

**轻量级存在性检查工具**，支持双引擎快速计数。

#### ToolDefinition

```python
ToolDefinition(
    name="grep_count",
    description=(
        "Quickly count pattern matches across files. "
        "Use BEFORE grep_search to check if a pattern exists. "
        "Supports both text mode (regex) and AST mode (structural). "
        "Much faster than full search because it does not collect context."
    ),
    parameters=[
        ToolParameter(
            name="pattern",
            type=ToolParameterType.STRING,
            description="Search pattern (regex or AST meta-variable pattern)",
            required=True,
        ),
        ToolParameter(
            name="lang",
            type=ToolParameterType.STRING,
            description="Programming language for AST search. Forces AST engine.",
            required=False,
        ),
        ToolParameter(
            name="search_dir",
            type=ToolParameterType.STRING,
            description="Directory to search. Default: '.'",
            required=False,
            default=".",
        ),
        ToolParameter(
            name="include",
            type=ToolParameterType.STRING,
            description="Glob pattern to filter files. Default: '*'",
            required=False,
            default="*",
        ),
        ToolParameter(
            name="case_sensitive",
            type=ToolParameterType.BOOLEAN,
            description="Case sensitive search (text mode only). Default: False.",
            required=False,
            default=False,
        ),
    ],
)
```

---

## 6. Hook 集成

### 6.1 register_tools

注册 `GrepSearchTool` 和 `GrepCountTool`。

### 6.2 get_system_prompt

注入统一搜索工具使用指南。

```python
@hookimpl
def get_system_prompt(self) -> str:
    return """## Code Search (Grep) — Unified Search

`grep_search` is your single tool for ALL code search needs. It automatically
chooses between text-level regex and AST-level structural matching.

### When to use each mode:

**Text mode** (default — just use regex):
- Comments, TODOs, string literals, log messages
- Simple keyword search
- Non-code files (.md, .json, .yaml)
- Example: `grep_search(pattern="TODO|FIXME|HACK")`

**AST mode** (use `$$$` or `lang` parameter):
- Code structure: function calls, class definitions, imports
- Patterns with specific argument structures
- Cross-line code blocks
- Example: `grep_search(pattern="fetch($URL, {method: 'POST'})", lang="typescript")`

**Quick check**: Use `grep_count` first to verify a pattern exists before full search.

Default excludes: .git, node_modules, .venv, __pycache__, dist, build
"""
```

### 6.3 enhance_tool_error

增强双引擎错误信息。

```python
@hookimpl
def enhance_tool_error(
    self,
    tool_name: str,
    arguments: Dict[str, Any],
    error_info: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    if tool_name == "grep_search":
        error_msg = error_info.get("error", "").lower()
        
        # Text engine errors
        if "invalid regex" in error_msg or "regex" in error_msg:
            return {
                "error_type": "grep_invalid_regex",
                "diagnosis": "The search pattern is not a valid regular expression.",
                "fix_suggestions": [
                    "Check for unescaped special characters",
                    "Use raw strings: r'pattern' instead of 'pattern'",
                    "Escape dots: use '\\.' for literal dots",
                ],
                "confidence": 0.95,
            }
        
        # AST engine errors
        if "ast" in error_msg or "parse" in error_msg or "syntax" in error_msg:
            return {
                "error_type": "grep_ast_parse_error",
                "diagnosis": "AST engine failed to parse the pattern or source file.",
                "fix_suggestions": [
                    "Ensure pattern is a valid AST node (complete code snippet)",
                    "Meta-variables: $VAR for single node, $$$ for multiple nodes",
                    "Verify the `lang` parameter matches the file type",
                    "Try text mode: remove `lang` and use regex instead",
                ],
                "confidence": 0.9,
            }
        
        if "no matches" in error_msg or "0 matches" in error_msg:
            lang = arguments.get("lang")
            suggestions = [
                "Try a simpler pattern",
                "Check if include glob pattern is too restrictive",
                "Verify search_dir exists and contains files",
            ]
            if lang:
                suggestions.append(
                    f"AST search for '{lang}' found nothing — try text mode (remove lang parameter)"
                )
            else:
                suggestions.append(
                    "Try AST mode: add `lang` parameter or use meta-variables ($$$)"
                )
            return {
                "error_type": "grep_no_matches",
                "diagnosis": "No matches found with the current pattern and engine.",
                "fix_suggestions": suggestions,
                "confidence": 0.85,
            }
    
    return None

@hookimpl
def enhance_tool_error_priority(self) -> int:
    return 50
```

---

## 7. 数据结构

### 7.1 Match

统一匹配结果（两种引擎共享）。

```python
@dataclass
class Match:
    """Single match result (unified for both engines)."""
    file: str
    line: int
    content: str
    context_before: List[str] = field(default_factory=list)
    context_after: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "file": self.file,
            "line": self.line,
            "content": self.content,
            "context_before": self.context_before,
            "context_after": self.context_after,
        }
```

### 7.2 SearchResult

```python
@dataclass
class SearchResult:
    """Complete search result."""
    pattern: str
    search_dir: str
    total_matches: int
    files_searched: int
    files_matched: int
    matches: List[Match]
    truncated: bool = False
    engine: str = "text"  # "text" | "ast" — 标记使用的引擎
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern": self.pattern,
            "search_dir": self.search_dir,
            "engine": self.engine,
            "total_matches": self.total_matches,
            "files_searched": self.files_searched,
            "files_matched": self.files_matched,
            "matches": [m.to_dict() for m in self.matches],
            "truncated": self.truncated,
        }
```

### 7.3 SearchConfig

```python
class SearchConfig:
    DEFAULT_EXCLUDE_DIRS: List[str] = [
        ".git", "node_modules", ".venv", "__pycache__",
        "dist", "build", ".tox", ".mypy_cache",
        ".pytest_cache", ".ruff_cache", "venv", "env",
    ]
    DEFAULT_MAX_RESULTS: int = 100
    DEFAULT_TIMEOUT: float = 10.0
    MAX_FILE_SIZE: int = 10 * 1024 * 1024  # 10MB (text engine)
    MAX_AST_FILE_SIZE: int = 2 * 1024 * 1024  # 2MB (AST engine, smaller for parsing)
```

---

## 8. 包结构

### 8.1 pyproject.toml

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "py-code-agent-grep"
version = "0.1.0"
description = "Unified code search plugin for Py Code Agent — regex + AST structural search"
readme = "README.md"
requires-python = ">=3.10"
license = {text = "MIT"}
authors = [
    {name = "Py Code Agent Team"}
]
keywords = ["py-code-agent", "plugin", "grep", "search", "code-search", "ast-grep"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
]

dependencies = [
    "ast-grep-py>=0.42.0",  # AST search engine (PyO3 binding)
]

[project.optional-dependencies]
all = [
    "ast-grep-py>=0.42.0",
]
text-only = []  # Text engine only, no AST dependency

[project.entry-points."py_code_agent.plugins"]
grep = "py_code_agent_grep.plugin:GrepPlugin"

[tool.hatch.build.targets.wheel]
packages = ["py_code_agent_grep"]
```

### 8.2 plugin.py

```python
from __future__ import annotations

from typing import Any, Dict, List, Optional

from py_code_agent.plugins.hooks import hookimpl
from py_code_agent.tools.base import BaseTool

from py_code_agent_grep.tools import GrepCountTool, GrepSearchTool


class GrepPlugin:
    """Unified code search plugin — text regex + AST structural search.
    
    Provides a single search interface that automatically chooses between:
    - Text engine: regex-based line-by-line scanning (fast, universal)
    - AST engine: structural pattern matching via ast-grep-py (precise, language-aware)
    
    Dependencies:
        - ast-grep-py>=0.42.0: AST search engine (PyO3 binding)
    
    Tools:
        grep_search: Unified search with auto engine selection
        grep_count: Quick match count for existence checks
    """

    @hookimpl
    def register_tools(self) -> List[BaseTool]:
        return [GrepSearchTool(), GrepCountTool()]

    @hookimpl
    def get_system_prompt(self) -> str:
        # 见 6.2 节
        ...

    @hookimpl
    def enhance_tool_error(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        error_info: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        # 见 6.3 节
        ...

    @hookimpl
    def enhance_tool_error_priority(self) -> int:
        return 50
```

### 8.3 engine.py — 统一搜索接口

```python
"""Unified search engine — routes between TextEngine and AstEngine."""

from typing import Any, Dict, List, Optional

from py_code_agent_grep.ast_engine import AstEngine
from py_code_agent_grep.text_engine import TextEngine
from py_code_agent_grep.engine_router import EngineRouter
from py_code_agent_grep.types import SearchResult


class SearchEngine:
    """Unified search interface with automatic engine selection.
    
    Usage:
        # Auto-select engine based on pattern
        result = SearchEngine.search("def $FUNC($$$):")  # → AST engine
        
        # Force text engine
        result = SearchEngine.search("TODO|FIXME")  # → Text engine
        
        # Force AST engine via lang parameter
        result = SearchEngine.search("console.log($$$)", lang="typescript")  # → AST engine
    """

    @staticmethod
    def search(
        pattern: str,
        search_dir: str = ".",
        lang: Optional[str] = None,
        include: str = "*",
        exclude_dirs: Optional[List[str]] = None,
        case_sensitive: bool = False,
        context_before: int = 0,
        context_after: int = 0,
        max_results: int = 100,
    ) -> SearchResult:
        """Search code with automatic engine selection."""
        engine = EngineRouter.select(pattern, lang, include)
        
        if engine == "ast":
            return AstEngine.search(
                pattern=pattern,
                search_dir=search_dir,
                lang=lang,
                include=include,
                exclude_dirs=exclude_dirs,
                context_before=context_before,
                context_after=context_after,
                max_results=max_results,
            )
        else:
            return TextEngine.search(
                pattern=pattern,
                search_dir=search_dir,
                include=include,
                exclude_dirs=exclude_dirs,
                case_sensitive=case_sensitive,
                context_before=context_before,
                context_after=context_after,
                max_results=max_results,
            )

    @staticmethod
    def count(
        pattern: str,
        search_dir: str = ".",
        lang: Optional[str] = None,
        include: str = "*",
        exclude_dirs: Optional[List[str]] = None,
        case_sensitive: bool = False,
    ) -> Dict[str, Any]:
        """Quick count with automatic engine selection."""
        engine = EngineRouter.select(pattern, lang, include)
        
        if engine == "ast":
            return AstEngine.count(
                pattern=pattern,
                search_dir=search_dir,
                lang=lang,
                include=include,
                exclude_dirs=exclude_dirs,
            )
        else:
            return TextEngine.count(
                pattern=pattern,
                search_dir=search_dir,
                include=include,
                exclude_dirs=exclude_dirs,
                case_sensitive=case_sensitive,
            )
```

### 8.4 text_engine.py — 文本搜索引擎

```python
"""Text-based search engine — regex line-by-line scanning."""

import os
import re
from pathlib import Path
from typing import Iterator, List, Optional

from py_code_agent_grep.types import Match, SearchConfig, SearchResult
from py_code_agent_grep.file_scanner import FileScanner


class TextEngine:
    """Regex-based text search engine. Zero external dependencies."""

    @staticmethod
    def search(
        pattern: str,
        search_dir: str = ".",
        include: str = "*",
        exclude_dirs: Optional[List[str]] = None,
        case_sensitive: bool = False,
        context_before: int = 0,
        context_after: int = 0,
        max_results: int = 100,
    ) -> SearchResult:
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            compiled = re.compile(pattern, flags)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern: {e}")

        matches: List[Match] = []
        files_searched = 0
        files_matched_set: set[str] = set()
        total_matches = 0
        
        for fpath in FileScanner.discover(search_dir, include, exclude_dirs):
            files_searched += 1
            file_matches = _search_file(
                fpath, compiled, context_before, context_after
            )
            if file_matches:
                files_matched_set.add(str(fpath))
                for m in file_matches:
                    total_matches += 1
                    if len(matches) < max_results:
                        matches.append(m)

        return SearchResult(
            pattern=pattern,
            search_dir=str(Path(search_dir).resolve()),
            total_matches=total_matches,
            files_searched=files_searched,
            files_matched=len(files_matched_set),
            matches=matches,
            truncated=total_matches > max_results,
            engine="text",
        )

    @staticmethod
    def count(
        pattern: str,
        search_dir: str = ".",
        include: str = "*",
        exclude_dirs: Optional[List[str]] = None,
        case_sensitive: bool = False,
    ) -> Dict[str, Any]:
        flags = 0 if case_sensitive else re.IGNORECASE
        compiled = re.compile(pattern, flags)
        
        total = 0
        files_searched = 0
        per_file: Dict[str, int] = {}
        
        for fpath in FileScanner.discover(search_dir, include, exclude_dirs):
            files_searched += 1
            count = 0
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if compiled.search(line):
                            count += 1
            except (OSError, UnicodeDecodeError):
                continue
            
            if count > 0:
                total += count
                per_file[str(fpath)] = count

        return {
            "total_matches": total,
            "files_searched": files_searched,
            "files_matched": len(per_file),
            "per_file": per_file,
            "engine": "text",
        }


def _search_file(
    fpath: Path,
    compiled: re.Pattern,
    ctx_before: int,
    ctx_after: int,
) -> List[Match]:
    matches = []
    try:
        with open(fpath, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except (OSError, UnicodeDecodeError):
        return []

    for i, line in enumerate(lines):
        if compiled.search(line):
            before = [l.rstrip("\n") for l in lines[max(0, i - ctx_before):i]]
            after = [l.rstrip("\n") for l in lines[i + 1:i + 1 + ctx_after]]
            matches.append(Match(
                file=str(fpath),
                line=i + 1,
                content=line.rstrip("\n"),
                context_before=before,
                context_after=after,
            ))
    
    return matches
```

### 8.5 file_scanner.py — 文件发现 + 过滤

```python
"""File discovery with glob filtering and directory exclusion."""

import os
from pathlib import Path
from typing import Iterator, List, Optional

from py_code_agent_grep.types import SearchConfig


class FileScanner:
    """Discover files matching include/exclude patterns."""

    @staticmethod
    def discover(
        search_dir: str,
        include: str = "*",
        exclude_dirs: Optional[List[str]] = None,
    ) -> Iterator[Path]:
        base = Path(search_dir).resolve()
        if not base.is_dir():
            return
        
        excludes = set(exclude_dirs or SearchConfig.DEFAULT_EXCLUDE_DIRS)
        
        for root, dirs, files in os.walk(base):
            # 排除目录
            dirs[:] = [d for d in dirs if d not in excludes]
            
            for fname in files:
                fpath = Path(root) / fname
                
                # 应用 include glob
                if not _match_glob(fpath.name, include):
                    continue
                
                # 文件大小检查
                try:
                    if fpath.stat().st_size > SearchConfig.MAX_FILE_SIZE:
                        continue
                except OSError:
                    continue
                
                yield fpath


def _match_glob(filename: str, pattern: str) -> bool:
    """Support simple glob and brace expansion patterns."""
    from fnmatch import fnmatch
    
    # Handle brace expansion: *.{py,ts} → *.py, *.ts
    if "{" in pattern and "}" in pattern:
        import re
        match = re.match(r"(.*)\{(.+)\}(.*)", pattern)
        if match:
            prefix, alternatives, suffix = match.groups()
            for alt in alternatives.split(","):
                if fnmatch(filename, f"{prefix}{alt.strip()}{suffix}"):
                    return True
            return False
    
    return fnmatch(filename, pattern)
```

### 8.6 tools.py — 工具实现

```python
from __future__ import annotations

from typing import Any, Dict, List, Optional

from py_code_agent.tools.base import (
    BaseTool,
    ToolDefinition,
    ToolParameter,
    ToolParameterType,
    ToolResult,
)

from py_code_agent_grep.engine import SearchEngine


class GrepSearchTool(BaseTool):
    """Unified code search with auto engine selection."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="grep_search",
            description=(
                "Unified code search — supports both regex text search and AST structural search. "
                "Engine is automatically selected: meta-variables ($$$) or `lang` → AST, otherwise text."
            ),
            parameters=[
                # 见 5.1 节完整参数定义
                ToolParameter(
                    name="pattern",
                    type=ToolParameterType.STRING,
                    description="Search pattern (regex or AST meta-variable pattern)",
                    required=True,
                ),
                ToolParameter(
                    name="lang",
                    type=ToolParameterType.STRING,
                    description="Programming language for AST search. Forces AST engine.",
                    required=False,
                ),
                ToolParameter(
                    name="search_dir",
                    type=ToolParameterType.STRING,
                    description="Directory to search. Default: '.'",
                    required=False,
                    default=".",
                ),
                ToolParameter(
                    name="include",
                    type=ToolParameterType.STRING,
                    description="Glob pattern to filter files. Default: '*'",
                    required=False,
                    default="*",
                ),
                ToolParameter(
                    name="exclude_dirs",
                    type=ToolParameterType.ARRAY,
                    description="Directories to exclude.",
                    required=False,
                ),
                ToolParameter(
                    name="case_sensitive",
                    type=ToolParameterType.BOOLEAN,
                    description="Case sensitive (text mode only). Default: False.",
                    required=False,
                    default=False,
                ),
                ToolParameter(
                    name="context_before",
                    type=ToolParameterType.INTEGER,
                    description="Lines before each match. Default: 0.",
                    required=False,
                    default=0,
                ),
                ToolParameter(
                    name="context_after",
                    type=ToolParameterType.INTEGER,
                    description="Lines after each match. Default: 0.",
                    required=False,
                    default=0,
                ),
                ToolParameter(
                    name="max_results",
                    type=ToolParameterType.INTEGER,
                    description="Max matches to return. Default: 100.",
                    required=False,
                    default=100,
                ),
            ],
        )

    async def execute(
        self,
        pattern: str,
        lang: Optional[str] = None,
        search_dir: str = ".",
        include: str = "*",
        exclude_dirs: Optional[List[str]] = None,
        case_sensitive: bool = False,
        context_before: int = 0,
        context_after: int = 0,
        max_results: int = 100,
        **kwargs: Any,
    ) -> ToolResult:
        try:
            result = SearchEngine.search(
                pattern=pattern,
                search_dir=search_dir,
                lang=lang,
                include=include,
                exclude_dirs=exclude_dirs,
                case_sensitive=case_sensitive,
                context_before=context_before,
                context_after=context_after,
                max_results=max_results,
            )

            if result.total_matches == 0:
                engine_hint = f" ({result.engine} engine)"
                return ToolResult.fail(
                    f"No matches for pattern '{pattern}'{engine_hint} "
                    f"({result.files_searched} files searched)"
                )

            summary = (
                f"Found {result.total_matches} matches across "
                f"{result.files_matched} files ({result.engine} engine, "
                f"{result.files_searched} searched)"
            )
            if result.truncated:
                summary += f" (showing first {max_results})"

            return ToolResult.ok(data=result.to_dict(), summary=summary)

        except ValueError as e:
            return ToolResult.fail(f"Invalid pattern: {e}")
        except Exception as e:
            return ToolResult.fail(f"Search error: {e}")


class GrepCountTool(BaseTool):
    """Quick match count with auto engine selection."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="grep_count",
            description=(
                "Quickly count pattern matches. Use BEFORE grep_search. "
                "Supports both text (regex) and AST (structural) modes."
            ),
            parameters=[
                ToolParameter(
                    name="pattern",
                    type=ToolParameterType.STRING,
                    description="Search pattern (regex or AST meta-variable pattern)",
                    required=True,
                ),
                ToolParameter(
                    name="lang",
                    type=ToolParameterType.STRING,
                    description="Programming language for AST search. Forces AST engine.",
                    required=False,
                ),
                ToolParameter(
                    name="search_dir",
                    type=ToolParameterType.STRING,
                    description="Directory to search. Default: '.'",
                    required=False,
                    default=".",
                ),
                ToolParameter(
                    name="include",
                    type=ToolParameterType.STRING,
                    description="Glob pattern to filter files. Default: '*'",
                    required=False,
                    default="*",
                ),
                ToolParameter(
                    name="case_sensitive",
                    type=ToolParameterType.BOOLEAN,
                    description="Case sensitive (text mode only). Default: False.",
                    required=False,
                    default=False,
                ),
            ],
        )

    async def execute(
        self,
        pattern: str,
        lang: Optional[str] = None,
        search_dir: str = ".",
        include: str = "*",
        case_sensitive: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        try:
            result = SearchEngine.count(
                pattern=pattern,
                search_dir=search_dir,
                lang=lang,
                include=include,
                case_sensitive=case_sensitive,
            )

            if result["total_matches"] == 0:
                engine_hint = f" ({result.get('engine', 'text')} engine)"
                return ToolResult.fail(
                    f"No matches for '{pattern}'{engine_hint} "
                    f"({result['files_searched']} files searched)"
                )

            summary = f"{result['total_matches']} matches in {result['files_matched']} files"
            return ToolResult.ok(data=result, summary=summary)

        except ValueError as e:
            return ToolResult.fail(f"Invalid pattern: {e}")
        except Exception as e:
            return ToolResult.fail(f"Count error: {e}")
```

---

## 9. 错误处理

### 9.1 错误分类

| 错误类型 | 引擎 | 场景 | 处理方式 |
|----------|------|------|----------|
| `invalid_regex` | Text | 正则表达式无效 | ToolResult.fail + 修复建议 |
| `invalid_ast_pattern` | AST | AST 模式语法错误 | ToolResult.fail + 元变量说明 |
| `unsupported_language` | AST | 文件类型不在 25 种支持语言中 | 跳过文件，继续搜索 |
| `ast_parse_error` | AST | 文件无法解析为 AST | 跳过文件，降级到文本搜索 |
| `no_matches` | 共享 | 搜索无结果 | ToolResult.fail + 引擎切换建议 |
| `permission_denied` | 共享 | 文件访问权限不足 | 跳过文件 |
| `file_too_large` | 共享 | 文件超过大小限制 | 跳过 (Text: 10MB, AST: 2MB) |
| `encoding_error` | 共享 | 非 UTF-8 文件 | `errors="replace"` 降级 |
| `ast_grep_not_installed` | AST | `ast-grep-py` 未安装 | ToolResult.fail + 安装指引 |

### 9.2 AST 引擎降级策略

当 AST 引擎失败时，自动降级到文本引擎：

```python
def search_with_fallback(pattern, lang=None, **kwargs):
    """Try AST first, fall back to text engine."""
    if lang:
        try:
            return AstEngine.search(pattern=pattern, lang=lang, **kwargs)
        except Exception:
            # AST failed → fall back to text
            return TextEngine.search(pattern=pattern, **kwargs)
    
    # No lang specified → use router
    engine = EngineRouter.select(pattern, lang)
    if engine == "ast":
        try:
            return AstEngine.search(pattern=pattern, **kwargs)
        except Exception:
            return TextEngine.search(pattern=pattern, **kwargs)
    return TextEngine.search(pattern=pattern, **kwargs)
```

### 9.3 安全约束

- **路径遍历防护**: `Path(search_dir).resolve()` 确保搜索目录在工作目录内
- **文件大小限制**: Text 引擎 10MB / AST 引擎 2MB
- **目录排除**: 默认排除 12 个常见目录
- **编码安全**: `errors="replace"` 处理非 UTF-8 文件

---

## 10. 测试策略

### 10.1 单元测试

| 测试文件 | 覆盖内容 |
|----------|----------|
| `test_text_engine.py` | TextEngine.search(), TextEngine.count(), 正则匹配, 上下文行 |
| `test_ast_engine.py` | AstEngine.search(), AstEngine.count(), 元变量匹配, 语言检测 |
| `test_engine_router.py` | EngineRouter.select() 所有规则路径 |
| `test_search_engine.py` | SearchEngine 统一接口, 引擎切换, 降级策略 |
| `test_file_scanner.py` | FileScanner.discover(), glob 过滤, 目录排除, 大小限制 |
| `test_tools.py` | GrepSearchTool.execute(), GrepCountTool.execute() |
| `test_plugin.py` | GrepPlugin.register_tools(), get_system_prompt() |
| `test_types.py` | Match.to_dict(), SearchResult.to_dict() |

### 10.2 测试场景

```python
# ========== Text Engine Tests ==========

def test_text_search_def_pattern(sample_project):
    result = TextEngine.search(r"def \w+\(\)", search_dir=str(sample_project))
    assert result.total_matches == 3
    assert result.engine == "text"

def test_text_search_case_insensitive(sample_project):
    result = TextEngine.search("HELLO", search_dir=str(sample_project))
    assert result.total_matches > 0

def test_text_search_context_lines(sample_project):
    result = TextEngine.search(
        r"print\(", search_dir=str(sample_project),
        context_before=1, context_after=1,
    )
    for m in result.matches:
        assert len(m.context_before) >= 1
        assert len(m.context_after) >= 1

# ========== AST Engine Tests ==========

def test_ast_search_function_def(sample_project):
    result = AstEngine.search(
        "def $NAME($$$):", search_dir=str(sample_project), lang="python"
    )
    assert result.total_matches >= 3
    assert result.engine == "ast"

def test_ast_search_with_metavariable(sample_project):
    result = AstEngine.search(
        "print($MSG)", search_dir=str(sample_project), lang="python"
    )
    assert result.total_matches >= 2

def test_ast_count(sample_project):
    result = AstEngine.count(
        "def $NAME($$$):", search_dir=str(sample_project), lang="python"
    )
    assert result["total_matches"] >= 3

def test_language_detection():
    from py_code_agent_grep.ast_engine import _detect_language
    from pathlib import Path
    
    assert _detect_language(Path("test.py")) == "python"
    assert _detect_language(Path("test.tsx")) == "typescript"
    assert _detect_language(Path("test.unknown")) is None

# ========== Engine Router Tests ==========

def test_router_meta_variable_triggers_ast():
    assert EngineRouter.select("def $FUNC($$$):") == "ast"
    assert EngineRouter.select("console.log($$$)") == "ast"

def test_router_lang_forces_ast():
    assert EngineRouter.select("def hello()", lang="python") == "ast"

def test_router_default_to_text():
    assert EngineRouter.select("TODO|FIXME") == "text"
    assert EngineRouter.select("def test_") == "text"

def test_router_non_code_files():
    assert EngineRouter.select(".*", include="*.md") == "text"

# ========== Unified SearchEngine Tests ==========

def test_unified_auto_select_ast():
    result = SearchEngine.search("def $NAME($$$):", lang="python")
    assert result.engine == "ast"

def test_unified_auto_select_text():
    result = SearchEngine.search("TODO|FIXME")
    assert result.engine == "text"

# ========== File Scanner Tests ==========

def test_file_scanner_exclude_dirs(sample_project):
    files = list(FileScanner.discover(str(sample_project)))
    assert all(".git" not in str(f) for f in files)
    assert all("node_modules" not in str(f) for f in files)

def test_file_scanner_glob_filter(sample_project):
    files = list(FileScanner.discover(str(sample_project), include="*.py"))
    assert all(f.suffix == ".py" for f in files)

def test_file_scanner_brace_expansion():
    from py_code_agent_grep.file_scanner import _match_glob
    assert _match_glob("test.py", "*.{py,ts}")
    assert _match_glob("test.ts", "*.{py,ts}")
    assert not _match_glob("test.js", "*.{py,ts}")
```

### 10.3 集成测试

- 插件加载测试：通过 PluginManager 加载 GrepPlugin
- 双引擎注册测试：确认 grep_search 和 grep_count 被注册
- 端到端测试：模拟 Agent 调用 grep_search 并验证引擎自动选择
- 降级测试：AST 引擎失败时自动降级到文本引擎

---

## 11. 发布计划

### 11.1 版本规划

| 版本 | 功能 | 时间 |
|------|------|------|
| 0.1.0 | TextEngine + AstEngine 双引擎 + 自动路由 | 第 1-2 周 |
| 0.2.0 | AST 降级策略 + 超时控制 + 二进制文件检测 | 第 3 周 |
| 0.3.0 | 搜索结果缓存 + 增量搜索 + text-only 可选安装 | 第 4 周 |

### 11.2 发布检查清单

- [ ] TextEngine 实现完成
- [ ] AstEngine 实现完成（ast-grep-py 集成）
- [ ] EngineRouter 自动选择逻辑完成
- [ ] 降级策略实现并测试
- [ ] 单元测试覆盖率 > 80%
- [ ] 集成测试通过
- [ ] README.md 编写完成
- [ ] pyproject.toml 配置正确（含 ast-grep-py 依赖）
- [ ] Entry Point 注册验证
- [ ] 手动安装测试（`pip install -e .`）
- [ ] 与 Py Code Agent 集成测试
- [ ] text-only 可选依赖测试（`pip install py-code-agent-grep[text-only]`）

### 11.3 安装方式

```bash
# 完整版（文本 + AST 双引擎）
pip install py-code-agent-grep

# 仅文本引擎（无 AST 依赖，更轻量）
pip install py-code-agent-grep[text-only]

# 从源码
pip install -e ./py-code-agent-grep

# 通过 CLI
pi-code-agent plugin install py-code-agent-grep
```

---

## 12. 附录

### A. 引擎选择决策树

```
用户调用 grep_search(pattern, lang?, include?)
    │
    ├── 包含 $$$ 或 $VAR?
    │   └─ YES → AstEngine
    │
    ├── 指定了 lang 参数?
    │   └─ YES → AstEngine
    │
    ├── include 匹配非代码文件 (*.md, *.txt, *.json)?
    │   └─ YES → TextEngine
    │
    ├── pattern 匹配注释/字符串特征 (TODO, FIXME, 引号)?
    │   └─ YES → TextEngine
    │
    └─ 默认 → TextEngine (更快, 更通用)
```

### B. 双引擎能力矩阵

| 场景 | TextEngine | AstEngine | 推荐 |
|------|:---:|:---:|:---:|
| 查找注释/TODO | ✅ | ❌ | Text |
| 查找字符串内容 | ✅ | ❌ | Text |
| 查找函数定义 | ✅ | ✅ | Text (更快) |
| 查找函数调用 (忽略格式差异) | ⚠️ 脆弱 | ✅ 精确 | AST |
| 查找特定参数模式的调用 | ❌ 几乎不可能 | ✅ | AST |
| 查找跨多行的代码块 | ⚠️ 正则脆弱 | ✅ | AST |
| 非代码文件搜索 (.md, .json) | ✅ | ❌ | Text |
| 快速存在性检查 | ✅ 极快 | ✅ 快速 | Text |

### C. ast-grep-py 依赖说明

| 属性 | 值 |
|------|-----|
| 包名 | `ast-grep-py` |
| 当前版本 | 0.42.0 (2026-03-16) |
| 实现方式 | PyO3 (Rust → Python 原生绑定) |
| 安装方式 | `pip install ast-grep-py` |
| Python 支持 | 3.10 - 3.14 |
| 平台支持 | Linux (x86_64, aarch64), macOS (x86_64, arm64), Windows (x86, x64) |
| 许可 | MIT |
| 二进制大小 | ~5MB per wheel |
| 外部依赖 | 无 (Rust 编译到 wheel 中) |

### D. 性能基准（预估）

| 场景 | 文件数 | 总大小 | TextEngine | AstEngine |
|------|--------|--------|------------|-----------|
| 小型项目 | 50 | 200KB | < 0.1s | < 0.3s |
| 中型项目 | 500 | 5MB | < 0.5s | < 2s |
| 大型项目 | 2000 | 20MB | < 2s | < 5s |
