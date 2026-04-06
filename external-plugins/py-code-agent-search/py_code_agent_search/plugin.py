from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import List

from py_code_agent.plugins.hooks import hookimpl
from py_code_agent.tools.base import (
    BaseTool,
    ToolDefinition,
    ToolParameter,
    ToolParameterType,
    ToolResult,
)


class SearchPlugin:
    @hookimpl
    def register_tools(self) -> List[BaseTool]:
        return [WebSearchTool()]

    @hookimpl
    def get_system_prompt(self) -> str:
        return """## Web Search

Use `web_search` when you need current or factual information that you cannot infer:
- Technology news, release notes, or version changes
- Documentation for unfamiliar libraries or APIs
- Error messages that you haven't seen before
- Any question where local context is insufficient."""


class WebSearchTool(BaseTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="web_search",
            description="Search the web and get top results. Use for factual queries, news, or when you need current information.",
            parameters=[
                ToolParameter(
                    name="query",
                    type=ToolParameterType.STRING,
                    description="Search query",
                    required=True,
                ),
                ToolParameter(
                    name="max_results",
                    type=ToolParameterType.INTEGER,
                    description="Maximum number of results",
                    required=False,
                    default=5,
                ),
            ],
        )

    async def execute(self, query: str, max_results: int = 5, **kwargs) -> ToolResult:
        try:
            url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json&no_html=1"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            lines = [f"Query: {query}", ""]

            if data.get("AbstractText"):
                lines.append(f"Summary: {data['AbstractText']}")
                if data.get("AbstractURL"):
                    lines.append(f"Source: {data['AbstractURL']}")

            topics = data.get("RelatedTopics", [])
            if topics:
                lines.append("")
                lines.append(f"Related Topics ({len(topics)}):")
                for topic in topics[:max_results]:
                    text = topic.get("Text", "")
                    if topic.get("Icon", {}).get("URL"):
                        text = text[:100] + "..." if len(text) > 100 else text
                    if text:
                        lines.append(f"  - {text}")

            if not lines or (len(lines) == 2 and not lines[1]):
                lines.append("No results found.")

            return ToolResult.ok(
                data={"query": query, "results": "\n".join(lines)},
                summary=f"Search for '{query}' returned {len(topics)} topics",
            )

        except urllib.error.URLError as e:
            return ToolResult.fail(f"Network error: {e}")
        except Exception as e:
            return ToolResult.fail(f"Search error: {e}")


Plugin = SearchPlugin
