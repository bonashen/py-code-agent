# py-code-agent-search

Search plugin for Py Code Agent - provides web search capabilities via DuckDuckGo.

## Features

- **Web Search**: Search the web using DuckDuckGo Instant Answer API
- **Current Information**: Get up-to-date factual information, news, and documentation
- **Related Topics**: Discover related topics and resources

## Installation

```bash
# Install from PyPI
pip install py-code-agent-search
```

## Configuration

In your `config.yaml`:

```yaml
plugins:
  enabled:
    - search
```

## Tools Provided

| Tool | Description |
|------|-------------|
| `web_search` | Search the web and get top results |

## Usage

```bash
> web_search query="Python 3.12 new features"
```

## Requirements

- Python 3.9+
- No additional dependencies (uses stdlib)