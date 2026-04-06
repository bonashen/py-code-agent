# py-code-agent-git

Git plugin for Py Code Agent - provides git status and repository information tools.

## Features

- **Git Status**: Get current branch, recent commits, and working tree status
- **Repository Context**: Automatically understand the repository state before making changes

## Installation

```bash
# Install from PyPI
pip install py-code-agent-git
```

## Configuration

In your `config.yaml`:

```yaml
plugins:
  enabled:
    - git
```

## Tools Provided

| Tool | Description |
|------|-------------|
| `git_status` | Get git status, branch, and recent commits of the current repository |

## Usage

The plugin automatically provides context about the git repository:

```
> git_status
Branch: main

Recent commits:
abc1234 Fix authentication issue
abc1235 Add new feature
abc1236 Refactor codebase

Status (clean):
 M modified_file.py
?? new_file.py
```