# py-code-agent-mcp-gateway

MCP Gateway plugin for Py Code Agent - connect MCP (Model Context Protocol) servers and expose their tools.

## Features

- **MCP Server Connection**: Connect to MCP servers via stdio transport
- **Tool Exposure**: Automatically expose all MCP server tools as Py Code Agent tools
- **Server Management**: List and call tools across multiple MCP servers
- **Dynamic Discovery**: Auto-discover available tools on server initialization

## Installation

```bash
# Install from PyPI
pip install py-code-agent-mcp-gateway

# Or install with extra dependencies
pip install py-code-agent-mcp-gateway[mcp]
```

## Configuration

In your `config.yaml`:

```yaml
plugins:
  gateway:
    mcp:
      servers:
        - name: filesystem
          command: npx
          args: ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
          enabled: true
        
        - name: brave-search
          command: npx
          args: ["-y", "@modelcontextprotocol/server-brave-search"]
          env:
            BRAVE_API_KEY: ${BRAVE_API_KEY}
          enabled: true
          
        - name: postgres
          command: npx
          args: ["-y", "@modelcontextprotocol/server-postgres", "postgresql://user:pass@host/db"]
          enabled: true
```

### Server Configuration Options

| Option | Type | Description |
|--------|------|-------------|
| `name` | string | Server name (unique identifier) |
| `command` | string | Executable command (e.g., npx, node, python) |
| `args` | list | Command arguments |
| `env` | dict | Environment variables (supports ${ENV_VAR}) |
| `transport` | string | Transport type (stdio, http) - default: stdio |
| `url` | string | URL for HTTP transport |
| `headers` | dict | HTTP headers |
| `enabled` | bool | Enable/disable server |

## Tools Provided

| Tool | Description |
|------|-------------|
| `mcp_list_servers` | List all connected MCP servers and their tools |
| `mcp_call_tool` | Call a specific MCP tool by server and tool name |
| `mcp_{server}_{tool}` | Auto-generated tools for each MCP server tool |

## Usage

### List Servers

```
> mcp_list_servers
```

Output:
```
## filesystem (3 tools)
  - mcp_filesystem_read_directory: Read a directory
  - mcp_filesystem_read_file: Read a file
  - mcp_filesystem_write_file: Write to a file

## brave-search (1 tool)
  - mcp_brave-search_search: Search the web
```

### Call Tool Directly

```
> mcp_call_tool server_name=filesystem tool_name=read_file path="/path/to/file.txt"
```

### Use Auto-generated Tool

```
> mcp_filesystem_read_file path="/path/to/file.txt"
```

## MCP Servers

This plugin connects to MCP (Model Context Protocol) servers. Popular MCP servers:

- `@modelcontextprotocol/server-filesystem` - File system operations
- `@modelcontextprotocol/server-brave-search` - Web search
- `@modelcontextprotocol/server-postgres` - PostgreSQL database
- `@modelcontextprotocol/server-github` - GitHub operations
- `@modelcontextprotocol/server-slack` - Slack integration

## Requirements

- Python 3.9+
- Py Code Agent core
- MCP server packages (installed separately)

## Troubleshooting

### Server fails to initialize

Check that:
1. The command (npx, node, etc.) is available
2. The MCP server package is installed
3. Required environment variables are set

### Tools not appearing

MCP tools are discovered when the agent starts. Make sure:
1. Server is enabled in config
2. Agent has been started after config change

## Related Links

- [MCP Specification](https://spec.modelcontextprotocol.io/)
- [MCP Server Implementations](https://github.com/modelcontextprotocol/servers)