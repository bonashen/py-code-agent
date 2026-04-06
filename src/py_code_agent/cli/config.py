"""Config CLI — get, set, list, unset, path."""

import re
import sys
from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.table import Table
from rich.syntax import Syntax

console = Console()


def _config_paths() -> list[tuple[str, Path]]:
    return [
        ("user",   Path.home() / ".config" / "py-code-agent" / "config.yaml"),
        ("local",  Path.cwd() / ".py-code-agent" / "config.yaml"),
    ]


def _find_config() -> tuple[Path, dict]:
    """Find the first existing config file and load it."""
    for label, p in _config_paths():
        if p.exists():
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            return p, data
    return _config_paths()[0][1], {}


def _flatten(data: dict, prefix: str = "") -> list[tuple[str, str]]:
    """Flatten nested dict into dot-key tuples."""
    items = []
    for k, v in data.items():
        full = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            items.extend(_flatten(v, full))
        elif isinstance(v, list):
            items.append((full, yaml.dump(v, default_flow_style=True).strip()))
        else:
            items.append((full, str(v)))
    return items


def _get_nested(data: dict, key: str) -> tuple[any, str]:
    """Get a value from nested dict by dot-separated key. Returns (value, path)."""
    keys = key.split(".")
    current = data
    for i, k in enumerate(keys):
        if not isinstance(current, dict) or k not in current:
            return None, ".".join(keys[:i]) or key
        current = current[k]
    return current, ""


def _set_nested(data: dict, key: str, value: str) -> None:
    """Set a value in nested dict by dot-separated key. Casts type."""
    keys = key.split(".")
    current = data
    for k in keys[:-1]:
        current = current.setdefault(k, {})
    last = keys[-1]
    casted = _cast_value(value)
    current[last] = casted


def _cast_value(value: str) -> any:
    """Cast string CLI value to appropriate Python type."""
    if value.lower() in ("true", "yes", "on"):
        return True
    if value.lower() in ("false", "no", "off"):
        return False
    if value.lower() == "null":
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


# ---------------------------------------------------------------------------
# config list
# ---------------------------------------------------------------------------

@click.command(name="list")
def list_config() -> None:
    """List all config keys and their current values."""
    path, data = _find_config()
    console.print(f"[dim]Config file:[/dim] {path}  {'[green](exists)[/green]' if path.exists() else '[yellow](not found)[/yellow]'}\n")

    if not data:
        console.print("[dim]Config is empty. Use [bold]config set[/bold] to add values.[/dim]")
        return

    table = Table(title="Configuration", style="cyan", show_header=True)
    table.add_column("Key", style="bold cyan")
    table.add_column("Value", style="green")
    table.add_column("Type", style="dim")

    for key, val in _flatten(data):
        t = type(val).__name__
        display = yaml.dump(val, default_flow_style=True).strip() if isinstance(val, (list, dict)) else str(val)
        table.add_row(key, display, t)

    console.print(table)


# ---------------------------------------------------------------------------
# config get
# ---------------------------------------------------------------------------

@click.command(name="get")
@click.argument("key")
def get_config(key: str) -> None:
    """Get a config value by dot-separated key (e.g. llm.model, plugins.enabled)."""
    path, data = _find_config()
    value, missing_at = _get_nested(data, key)

    if missing_at:
        console.print(f"[red]✗ Key not found — '{missing_at}' does not exist[/red]")
        console.print(f"[dim]Config file:[/dim] {path}")
        sys.exit(1)

    if isinstance(value, (dict, list)):
        yaml_str = yaml.dump(value, default_flow_style=False, allow_unicode=True)
        syntax = Syntax(yaml_str, "yaml", theme="monokai", line_numbers=False)
        console.print(syntax)
    else:
        console.print(f"[bold cyan]{key}[/bold cyan] = {value}")


# ---------------------------------------------------------------------------
# config set
# ---------------------------------------------------------------------------

@click.command(name="set")
@click.argument("key")
@click.argument("value")
@click.option("--local", is_flag=True, help="Set in ./.py-code-agent/config.yaml")
@click.option("--global", "is_global", is_flag=True, help="Set in ~/.config/py-code-agent/config.yaml")
def set_config(key: str, value: str, local: bool, is_global: bool) -> None:
    """Set a config value by dot-separated key.

    KEY is a dot-separated path (e.g. llm.model, plugins.enabled).
    VALUE is the new value — automatically cast to bool/int/float/str.

    Examples:
      config set llm.model gpt-4
      config set llm.temperature 0.5
      config set plugins.disabled "['file:log_plugin']"
      config set --global llm.base_url https://...
    """
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*$", key):
        console.print(f"[red]✗ Invalid key format:[/red] {key}")
        console.print("[dim]Keys must be dot-separated identifiers (e.g. llm.model)[/dim]")
        sys.exit(1)

    if is_global:
        target = Path.home() / ".config" / "py-code-agent" / "config.yaml"
    elif local:
        target = Path.cwd() / ".py-code-agent" / "config.yaml"
    else:
        target, _ = _find_config()
        if not target.exists():
            target = _config_paths()[0][1]

    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    else:
        data = {}

    old_val, _ = _get_nested(data, key)
    _set_nested(data, key, value)

    content = yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)
    target.write_text(content, encoding="utf-8")

    new_val, _ = _get_nested(data, key)
    console.print(f"[green]✓[/green] Set [bold cyan]{key}[/bold cyan] = {new_val}")
    console.print(f"[dim]Saved to:[/dim] {target}")

    if old_val != new_val:
        console.print(f"[dim]Previous value:[/dim] {old_val}")


# ---------------------------------------------------------------------------
# config unset
# ---------------------------------------------------------------------------

@click.command(name="unset")
@click.argument("key")
@click.option("--local", is_flag=True, help="Unset in ./.py-code-agent/config.yaml")
@click.option("--global", "is_global", is_flag=True, help="Unset in ~/.config/py-code-agent/config.yaml")
def unset_config(key: str, local: bool, is_global: bool) -> None:
    """Remove a config key from config.yaml."""
    if is_global:
        target = Path.home() / ".config" / "py-code-agent" / "config.yaml"
    elif local:
        target = Path.cwd() / ".py-code-agent" / "config.yaml"
    else:
        target, _ = _find_config()

    if not target.exists():
        console.print(f"[red]✗ Config file not found:[/red] {target}")
        sys.exit(1)

    data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    keys = key.split(".")
    current = data
    for k in keys[:-1]:
        if not isinstance(current, dict) or k not in current:
            console.print(f"[red]✗ Key not found:[/red] {key}")
            sys.exit(1)
        current = current[k]

    last = keys[-1]
    if last in current:
        del current[last]
        target.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False), encoding="utf-8")
        console.print(f"[green]✓[/green] Removed [bold cyan]{key}[/bold cyan] from {target}")
    else:
        console.print(f"[red]✗ Key not found:[/red] {key}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# config path
# ---------------------------------------------------------------------------

@click.command(name="path")
@click.option("--create", is_flag=True, help="Create the config file if it does not exist")
def config_path(create: bool) -> None:
    """Show the active config file path."""
    target, data = _find_config()

    if create and not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("plugins:\n  enabled: []\n  disabled: []\n", encoding="utf-8")
        console.print(f"[green]✓ Created:[/green] {target}")
    else:
        console.print(str(target))


# ---------------------------------------------------------------------------
# config init
# ---------------------------------------------------------------------------

@click.command(name="init")
@click.option("--force", is_flag=True, help="Overwrite existing config")
def config_init(force: bool) -> None:
    """Create a default config.yaml in ~/.config/py-code-agent/."""
    target = Path.home() / ".config" / "py-code-agent" / "config.yaml"
    default = """llm:
  provider: openai
  model: gpt-4
  api_key: ${PY_LLM_API_KEY}
  base_url: ${PY_LLM_BASE_URL}
  timeout: 60
  temperature: 0.7
  max_tokens: 4000

tools:
  enabled:
    - read_file
    - write_file
    - execute_bash
  timeout: 30
  allow_bash: true
  allowed_paths:
    - ./
  blocked_paths:
    - ~/.ssh
    - ~/.aws

ui:
  theme: dark
  show_tool_calls: true
  stream_output: true
  history_size: 1000

plugins:
  enabled: []
  disabled: []
"""

    if target.exists() and not force:
        console.print(f"[yellow]⚠ config.yaml already exists:[/yellow] {target}")
        console.print("[dim]Use --force to overwrite.[/dim]")
        sys.exit(1)

    target.write_text(default, encoding="utf-8")
    console.print(f"[green]✓ Initialized:[/green] {target}")
    console.print("[dim]Edit it and set your API key, then run:[/dim] py-code-agent chat")


# ---------------------------------------------------------------------------
# Command group
# ---------------------------------------------------------------------------

@click.group(name="config")
def config_group() -> None:
    """Manage configuration (get, set, list, unset, init, path)."""
    pass


config_group.add_command(list_config)
config_group.add_command(get_config)
config_group.add_command(set_config)
config_group.add_command(unset_config)
config_group.add_command(config_path)
config_group.add_command(config_init)
