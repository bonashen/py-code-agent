# Py Code Agent OMO

Oh My OpenCode plugin collection for Py Code Agent. Brings multi-model orchestration, parallel sub-agents, intent classification, and discipline enforcement.

## Features

| Plugin | Capability |
|--------|-----------|
| **Intent Gate** | Classifies user intent (research/implementation/fix/investigation/open-ended) before execution |
| **Category Router** | Maps task categories to optimal models (Gemini for visual, GPT for logic, Claude for deep) |
| **Sub-Agent** | Parallel background agent execution with category-based model routing |
| **Discipline** | Ralph Loop + Todo Enforcer — prevents agent from quitting with pending work |
| **Comment Checker** | Prevents AI-generated excessive comments in code |
| **Think Mode** | Structured thinking tool for complex problems |

## Installation

```bash
pip install py-code-agent-omo
```

Plugins are auto-discovered via entry points. No additional configuration needed.

## Configuration

Create `~/.config/py-code-agent/omo.yaml` to customize model assignments:

```yaml
category_router:
  categories:
    visual-engineering:
      model: "google/gemini-3.1-pro"
      variant: "high"
    ultrabrain:
      model: "openai/gpt-5.4"
      variant: "xhigh"
    quick:
      model: "openai/gpt-5.4-mini"
```

See `omo.yaml.example` for the full configuration reference.

## Tools Provided

| Tool | Plugin | Description |
|------|--------|-------------|
| `classify_intent` | Intent Gate | Classify task intent |
| `route_task` | Category Router | Resolve category → model |
| `list_categories` | Category Router | List available categories |
| `set_category_model` | Category Router | Override category model |
| `task` | Sub-Agent | Delegate to background agent |
| `background_output` | Sub-Agent | Get background task output |
| `background_cancel` | Sub-Agent | Cancel running task |
| `background_list` | Sub-Agent | List all background tasks |
| `check_todos` | Discipline | Check pending todo count |
| `enforce_continuation` | Discipline | Force continuation |
| `check_comment_ratio` | Comment Checker | Scan file comment ratio |
| `ultrathink` | Think Mode | Structured problem analysis |

## Usage

```python
# Delegate to a visual engineering sub-agent
task(category="visual-engineering", description="Redesign sidebar", prompt="...", run_in_background=True)

# Run a quick fix synchronously
task(category="quick", description="Fix typo in auth.py", prompt="...", run_in_background=False)

# Collect results
background_output(task_id="bg_abc123")

# Structured thinking for complex decisions
ultrathink(problem="Should we migrate from SQLite to Postgres?")
```

## Requirements

- Python 3.10+
- Py Code Agent 0.1.0+
- PyYAML 6.0+
- Pydantic 2.0+

## License

MIT
