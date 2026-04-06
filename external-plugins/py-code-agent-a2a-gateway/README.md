# py-code-agent-a2a-gateway

A2A Gateway plugin for Py Code Agent - enables agent-to-agent communication via A2A v0.3.0 protocol.

## Features

- **Agent Discovery**: Exposes `.well-known/agent-card.json` for agent capability discovery
- **JSON-RPC Communication**: Implements A2A v0.3.0 JSON-RPC protocol
- **Peer Management**: Configure and communicate with peer agents
- **SSE Streaming**: Supports server-sent events for streaming responses
- **Bearer Token Auth**: Optional authentication for secure agent communication

## Installation

```bash
# Install from PyPI
pip install py-code-agent-a2a-gateway

# Or install with extra dependencies
pip install py-code-agent-a2a-gateway[all]
```

## Configuration

In your `config.yaml`:

```yaml
plugins:
  gateway:
    a2a:
      host: "0.0.0.0"
      port: 18800
      name: "MyAgent"
      description: "My AI coding agent"
      token: ${A2A_TOKEN}  # Optional: supports ${ENV_VAR} substitution
      skills:
        - id: "coding"
          name: "Coding Assistant"
      peers:
        - name: "peer-agent"
          agentCardUrl: "http://localhost:18801/.well-known/agent-card.json"
          token: ${PEER_TOKEN}  # Optional
```

## Tools Provided

| Tool | Description |
|------|-------------|
| `a2a_list_peers` | List all configured A2A peer agents |
| `a2a_send_message` | Send a message to an A2A peer agent |
| `a2a_get_my_card` | Get this agent's A2A Agent Card |

## Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/.well-known/agent-card.json` | GET | Agent discovery |
| `/a2a/jsonrpc` | POST | JSON-RPC message handling |
| `/health` | GET | Health check |

## A2A Protocol

This plugin implements the [A2A Protocol v0.3.0](https://github.com/agent-protocol/a2a-protocol):

- **Agent Card**: Standardized agent capability description
- **JSON-RPC**: Message passing between agents
- **Streaming**: SSE support for streaming responses