"""Plugin CLI commands for Py Code Agent."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import click
import httpx
from rich.console import Console
from rich.table import Table

console = Console()


def _get_builtin_plugin_dir() -> Path:
    import py_code_agent
    return Path(py_code_agent.__file__).parent.parent.parent / "plugins" / "builtin"


def _get_global_plugin_dir() -> Path:
    return Path.home() / ".config" / "py-code-agent" / "plugins"


def _get_local_plugin_dir() -> Path:
    return Path.cwd() / ".py-code-agent" / "plugins"


def _get_entry_point_plugins() -> list:
    try:
        if sys.version_info >= (3, 10):
            from importlib.metadata import entry_points
        else:
            from importlib_metadata import entry_points

        eps = entry_points()
        if hasattr(eps, "select"):
            return list(eps.select(group="py_code_agent.plugins"))
        return eps.get("py_code_agent.plugins", [])
    except Exception:
        return []


def _find_installer() -> str:
    if shutil.which("uv"):
        return "uv"
    return "pip"


def _run_cmd(cmd: list[str]) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out after 120 seconds"
    except FileNotFoundError:
        return -1, "", f"Command not found: {cmd[0]}"
    except Exception as e:
        return -1, "", str(e)


# ---------------------------------------------------------------------------
# plugin install
# ---------------------------------------------------------------------------

@click.command(name="install")
@click.argument("package")
@click.option("--no-reload", is_flag=True, help="Skip plugin reload after install")
def install(package: str, no_reload: bool) -> None:
    """Install a plugin from PyPI, git URL, or local path."""
    installer = _find_installer()

    console.print(f"[dim]Using {installer} to install[/dim] [bold]{package}[/bold]...")

    if installer == "uv":
        cmd = ["uv", "pip", "install", package]
    else:
        cmd = [sys.executable, "-m", "pip", "install", package]

    code, stdout, stderr = _run_cmd(cmd)

    if code != 0:
        console.print(f"[red]✗ Installation failed:[/red] {stderr or stdout}")
        sys.exit(1)

    console.print(f"[green]✓ Installed[/green] {package}")

    eps = _get_entry_point_plugins()
    pkg_base = package.split("==")[0].split("@")[0].strip()
    matched = [ep for ep in eps if ep.name == pkg_base or pkg_base in ep.value]
    if matched:
        console.print(f"[green]✓ Plugin entry point verified:[/green] {matched[0].name}")
    else:
        console.print("[yellow]⚠ Plugin installed but entry point not found. "
                      "Make sure the package declares the 'py_code_agent.plugins' entry point.[/yellow]")


# ---------------------------------------------------------------------------
# plugin uninstall
# ---------------------------------------------------------------------------

@click.command(name="uninstall")
@click.argument("package")
def uninstall(package: str) -> None:
    """Uninstall a plugin package."""
    installer = _find_installer()
    pkg_name = package.split("==")[0].split("@")[0].strip()

    console.print(f"[dim]Uninstalling[/dim] [bold]{pkg_name}[/bold] via {installer}...")

    if installer == "uv":
        cmd = ["uv", "pip", "uninstall", "-y", pkg_name]
    else:
        cmd = [sys.executable, "-m", "pip", "uninstall", "-y", pkg_name]

    code, stdout, stderr = _run_cmd(cmd)

    if code != 0:
        console.print(f"[red]✗ Uninstallation failed:[/red] {stderr or stdout}")
        sys.exit(1)

    console.print(f"[green]✓ Uninstalled[/green] {pkg_name}")


# ---------------------------------------------------------------------------
# plugin list
# ---------------------------------------------------------------------------

@click.command(name="list")
def list_plugins() -> None:
    """List all installed plugins (entry points + built-in + local + global)."""
    # 1. Entry-point (PyPI) plugins
    eps = _get_entry_point_plugins()
    ep_table = Table(title="Entry Point Plugins (PyPI)", style="cyan")
    ep_table.add_column("Name", style="bold")
    ep_table.add_column("Module", style="dim")
    if eps:
        for ep in eps:
            ep_table.add_row(ep.name, ep.value)
    else:
        ep_table.add_row("[dim]No entry point plugins installed[/dim]", "")
    console.print(ep_table)

    # 2. Built-in plugins
    builtin_dir = _get_builtin_plugin_dir()
    # Show relative to repo root for clarity
    try:
        builtin_dir_relative = builtin_dir.relative_to(builtin_dir.parent.parent.parent)
    except ValueError:
        builtin_dir_relative = builtin_dir
    builtin_table = Table(title=f"Built-in Plugins ({builtin_dir_relative})", style="green")
    builtin_table.add_column("Name")
    builtin_table.add_column("Path")
    if builtin_dir.exists():
        found_builtin = False
        for p in sorted(builtin_dir.glob("*.py")):
            if p.name.startswith("_"):
                continue
            canonical = p.stem
            if canonical.endswith("_plugin"):
                canonical = canonical.removesuffix("_plugin")
            builtin_table.add_row(f"file:{canonical}", str(p.relative_to(builtin_dir.parent.parent)))
            found_builtin = True
        if not found_builtin:
            builtin_table.add_row("[dim]No built-in plugins[/dim]", "")
    else:
        builtin_table.add_row("[dim]No built-in plugins directory[/dim]", "")
    console.print(builtin_table)

    # 3. Local plugins
    local_dir = _get_local_plugin_dir()
    local_table = Table(title=f"Local Plugins ({local_dir})", style="yellow")
    local_table.add_column("Name")
    local_table.add_column("Path")
    if local_dir.exists():
        found_local = False
        for p in sorted(local_dir.iterdir()):
            if p.is_dir() and ((p / "__init__.py").exists() or (p / "plugin.py").exists()):
                local_table.add_row(p.name, str(p))
                found_local = True
            elif p.suffix == ".py":
                local_table.add_row(p.stem, str(p))
                found_local = True
        if not found_local:
            local_table.add_row("[dim]No local plugins[/dim]", "")
    else:
        local_table.add_row("[dim]No local plugins[/dim]", "")
    console.print(local_table)

    # 4. Global plugins
    global_dir = _get_global_plugin_dir()
    global_table = Table(title=f"Global Plugins ({global_dir})", style="magenta")
    global_table.add_column("Name")
    global_table.add_column("Path")
    if global_dir.exists():
        found_global = False
        for p in sorted(global_dir.iterdir()):
            if p.is_dir() and ((p / "__init__.py").exists() or (p / "plugin.py").exists()):
                global_table.add_row(p.name, str(p))
                found_global = True
            elif p.suffix == ".py":
                global_table.add_row(p.stem, str(p))
                found_global = True
        if not found_global:
            global_table.add_row("[dim]No global plugins[/dim]", "")
    else:
        global_table.add_row("[dim]No global plugins[/dim]", "")
    console.print(global_table)


# ---------------------------------------------------------------------------
# plugin search
# ---------------------------------------------------------------------------

@click.command(name="search")
@click.argument("query")
@click.option("--limit", "-n", default=10, help="Max results to show")
def search(query: str, limit: int) -> None:
    """Search PyPI for plugins matching QUERY."""
    url = "https://pypi.org/search/"
    console.print(f"[dim]Searching PyPI for:[/dim] [bold]{query}[/bold]")

    try:
        resp = httpx.get(
            "https://pypi.org/search/",
            params={"q": query, "o": "-z"},
            headers={"Accept": "application/vnd.pypiSEARCH.v1+json"},
            timeout=15,
        )
        if resp.status_code == 200:
            try:
                results = resp.json().get("objects", [])[:limit]
            except Exception:
                results = []
        else:
            results = []

    except httpx.RequestError:
        console.print("[red]✗ Network error — could not reach PyPI[/red]")
        console.print("[dim]Try: curl or browser → https://pypi.org/search/?q=<query>[/dim]")
        return

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return

    table = Table(title=f"PyPI Results for '{query}'")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Name", style="bold cyan")
    table.add_column("Version", style="green")
    table.add_column("Summary", style="dim")

    for i, r in enumerate(results, 1):
        table.add_row(
            str(i),
            r.get("name", ""),
            r.get("version", ""),
            r.get("summary", ""),
        )

    console.print(table)
    console.print(f"[dim]{len(results)} result(s)[/dim]")


# ---------------------------------------------------------------------------
# plugin info
# ---------------------------------------------------------------------------

@click.command(name="info")
@click.argument("package")
def info(package: str) -> None:
    """Show detailed info about a PyPI plugin package."""
    pkg_name = package.split("==")[0].strip()
    url = f"https://pypi.org/pypi/{pkg_name}/json"

    console.print(f"[dim]Fetching info from:[/dim] {url}")

    try:
        resp = httpx.get(url, timeout=15)
    except httpx.RequestError:
        console.print("[red]✗ Network error[/red]")
        return

    if resp.status_code == 404:
        console.print(f"[red]✗ Package not found on PyPI:[/red] {pkg_name}")
        return

    if resp.status_code != 200:
        console.print(f"[red]✗ PyPI returned status {resp.status_code}[/red]")
        return

    data = resp.json().get("info", {})

    from rich.panel import Panel
    from rich.text import Text

    fields = [
        ("Name", data.get("name", "")),
        ("Version", data.get("version", "")),
        ("Summary", data.get("summary", "")),
        ("Author", data.get("author", "")),
        ("Home Page", data.get("home_page", "") or data.get("project_url", "")),
        ("PyPI", f"https://pypi.org/project/{pkg_name}/"),
        ("License", data.get("license", "")),
        ("Requires Python", data.get("requires_python", "")),
    ]

    text = Text()
    for label, value in fields:
        if value:
            text.append(f"  {label}: ", style="bold")
            text.append(f"{value}\n")

    console.print(Panel(text, title=f"PyPI: {pkg_name}", border_style="cyan"))


# ---------------------------------------------------------------------------
# plugin init
# ---------------------------------------------------------------------------

@click.command(name="init")
@click.argument("name")
def init(name: str) -> None:
    """Scaffold a new plugin package in ~/.config/py-code-agent/plugins/NAME/."""
    if not name.isidentifier():
        console.print("[red]✗ Plugin name must be a valid Python identifier.[/red]")
        sys.exit(1)

    plugin_dir = _get_global_plugin_dir() / name

    if plugin_dir.exists():
        console.print(f"[red]✗ Plugin already exists:[/red] {plugin_dir}")
        sys.exit(1)

    plugin_dir.mkdir(parents=True, exist_ok=True)

    # __init__.py
    (_init_py := plugin_dir / "__init__.py").write_text(f'''"""Py Code Agent plugin: {name}."""

from .{name}_plugin import {name.title().replace("_", "")}Plugin

__all__ = ["{name.title().replace("_", "")}Plugin"]
''')

    # plugin.py skeleton
    class_name = "".join(p.title() for p in name.split("_"))
    (plugin_file := plugin_dir / f"{name}_plugin.py").write_text(f'''"""Plugin implementation for {name}."""

from typing import List

from py_code_agent.plugins.hooks import hookimpl
from py_code_agent.tools.base import BaseTool


class {class_name}:
    """Plugin: {name}."""

    @hookimpl
    def register_tools(self) -> List[BaseTool]:
        """Register plugin tools."""
        return []
''')

    # pyproject.toml with entry point
    (pyproj := plugin_dir / "pyproject.toml").write_text(f'''[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "{name}"
version = "0.1.0"
description = "Py Code Agent plugin: {name}"

[project.entry-points."py_code_agent.plugins"]
{name} = "{name}.{name}_plugin:{class_name}"
''')

    # README.md
    (readme := plugin_dir / "README.md").write_text(f'''# {name}

A Py Code Agent plugin.

## Installation

```bash
py-code-agent plugin install .
```

## Development

```bash
pip install -e .
```
''')

    console.print(f"[green]✓ Plugin scaffolded at:[/green] {plugin_dir}")
    console.print("[dim]Next steps:[/dim]")
    console.print(f"  cd {plugin_dir}")
    console.print(f"  # Edit {name}_plugin.py to add your plugin class")
    console.print(f"  # Edit pyproject.toml to set the correct entry point")


# ---------------------------------------------------------------------------
# plugin available — show all loadable sample plugins
# ---------------------------------------------------------------------------

@click.command(name="available")
def available() -> None:
    """List all available sample plugins that can be enabled."""

    def _discover_plugins() -> list[tuple[str, str, str]]:
        """Discover built-in plugins from the package's plugins/builtin/ directory."""
        import re

        plugins: list[tuple[str, str, str]] = []

        # Built-in plugins directory: repo/plugins/builtin/
        import py_code_agent
        pkg_root = Path(py_code_agent.__file__).parent.parent.parent
        builtin_dir = pkg_root / "plugins" / "builtin"

        if not builtin_dir.exists():
            return []

        for plugin_file in sorted(builtin_dir.glob("*.py")):
            if plugin_file.name.startswith("_"):
                continue

            try:
                content = plugin_file.read_text(encoding="utf-8")
                first_line = content.strip().split("\n")[0] if content.strip() else ""
                doc = first_line.strip().lstrip('"""').rstrip('"""').strip()
                if not doc:
                    doc = plugin_file.stem.replace("_", " ").replace("-", " ").title()

                # Extract class name from the file
                class_match = re.search(r"class\s+(\w+Plugin)\s*[:(]", content)
                class_name = class_match.group(1) if class_match else plugin_file.stem.title()

                plugin_name = f"file:{plugin_file.stem}"
                # Strip common _plugin suffix to get canonical name (e.g. a2a_gateway_plugin → a2a_gateway)
                canonical = plugin_file.stem
                if canonical.endswith("_plugin"):
                    canonical = canonical.removesuffix("_plugin")
                plugin_name = f"file:{canonical}"
                plugins.append((plugin_name, class_name, doc))
            except Exception:
                continue

        return plugins

    samples = _discover_plugins()

    if not samples:
        console.print("[yellow]No sample plugins found.[/yellow]")
        return

    table = Table(title="Available Sample Plugins", style="cyan")
    table.add_column("Name", style="bold cyan")
    table.add_column("Class", style="dim")
    table.add_column("Description")

    for name, cls, desc in samples:
        table.add_row(name, cls, desc)

    console.print(table)
    console.print("[dim]Enable with:[/dim] pi-code-agent plugin enable <name>")
    console.print("[dim]Disable with:[/dim] pi-code-agent plugin disable <name>")


# ---------------------------------------------------------------------------
# plugin enable / disable
# ---------------------------------------------------------------------------

def _find_config_path() -> Path:
    user = Path.home() / ".config" / "py-code-agent" / "config.yaml"
    if user.exists():
        return user
    local = Path.cwd() / ".py-code-agent" / "config.yaml"
    if local.exists():
        return local
    return user


def _patch_config_yaml(name: str, list_key: str, action: str) -> None:
    """Add or remove a plugin name from a list in config.yaml."""
    import re
    import yaml

    config_path = _find_config_path()

    if config_path.exists():
        content = config_path.read_text(encoding="utf-8")
    else:
        content = "plugins:\n  enabled: []\n  disabled: []\n"
        config_path.parent.mkdir(parents=True, exist_ok=True)

    data = yaml.safe_load(content) or {}
    plugins_cfg = data.setdefault("plugins", {})
    key = "enabled" if list_key == "enabled" else "disabled"
    plugin_list = plugins_cfg.setdefault(key, [])

    if action == "add":
        if name in plugin_list:
            console.print(f"[yellow]⚠ {name} is already in plugins.{key}[/yellow]")
            return
        plugin_list.append(name)
        console.print(f"[green]✓ Added[/green] {name} [dim]to plugins.{key}[/dim]")
    else:
        if name not in plugin_list:
            console.print(f"[yellow]⚠ {name} is not in plugins.{key}[/yellow]")
            return
        plugin_list.remove(name)
        console.print(f"[green]✓ Removed[/green] {name} [dim]from plugins.{key}[/dim]")

    config_path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    console.print(f"[dim]Saved to:[/dim] {config_path}")


@click.command(name="enable")
@click.argument("name")
@click.option("--global", "is_global", is_flag=True, help="Apply to ~/.py_code_agent/config.yaml instead of ./config.yaml")
def enable(name: str, is_global: bool) -> None:
    """Enable a plugin by adding it to plugins.enabled in config.yaml."""
    if is_global:
        global_path = Path.home() / ".py_code_agent" / "config.yaml"
        global_path.parent.mkdir(parents=True, exist_ok=True)
        _patch_config_global(name, "enabled", global_path)
    else:
        _patch_config_yaml(name, "enabled", "add")


@click.command(name="disable")
@click.argument("name")
@click.option("--global", "is_global", is_flag=True, help="Apply to ~/.py_code_agent/config.yaml instead of ./config.yaml")
def disable(name: str, is_global: bool) -> None:
    """Disable a plugin by adding it to plugins.disabled in config.yaml."""
    if is_global:
        global_path = Path.home() / ".py_code_agent" / "config.yaml"
        global_path.parent.mkdir(parents=True, exist_ok=True)
        _patch_config_global(name, "disabled", global_path)
    else:
        _patch_config_yaml(name, "disabled", "add")


def _patch_config_global(name: str, list_key: str, config_path: Path) -> None:
    """Patch global config file."""
    import re
    import yaml

    if config_path.exists():
        content = config_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content) or {}
    else:
        content = ""
        data = {}

    plugins_cfg = data.setdefault("plugins", {})
    plugin_list = plugins_cfg.setdefault(list_key, [])

    if name in plugin_list:
        console.print(f"[yellow]⚠ {name} is already in plugins.{list_key}[/yellow]")
        return

    plugin_list.append(name)
    console.print(f"[green]✓ Added[/green] {name} [dim]to plugins.{list_key}[/dim]")

    config_path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    console.print(f"[dim]Saved to:[/dim] {config_path}")


# ---------------------------------------------------------------------------
# Command group
# ---------------------------------------------------------------------------

@click.group(name="plugin")
def plugin_group() -> None:
    """Manage Py Code Agent plugins (install, uninstall, list, search, info, init, enable, disable)."""
    pass


plugin_group.add_command(install)
plugin_group.add_command(uninstall)
plugin_group.add_command(list_plugins, name="list")
plugin_group.add_command(search)
plugin_group.add_command(info)
plugin_group.add_command(init)
plugin_group.add_command(available)
plugin_group.add_command(enable)
plugin_group.add_command(disable)
