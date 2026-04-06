"""Configuration models using Pydantic with .env support."""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


def _expand_env_vars_in_content(content: str) -> str:
    """Expand ${VAR:-default} and ${VAR} patterns in YAML content strings.

    Supports:
      ${VAR}        - use env var, empty string if unset
      ${VAR:-def}   - use env var, fallback to 'def' if unset
    """

    def replacer(m: re.Match) -> str:
        var = m.group("var")
        raw_def = m.group("def")
        # raw_def may look like "-60" (leading dash) — strip it so defaults parse correctly
        default = raw_def.lstrip("-") if raw_def else ""
        return os.environ.get(var, default)

    pattern = r"\$\{(?P<var>[A-Za-z_][A-Za-z0-9_]*)(?:[:-](?P<def>[^}]*))?\}"
    return re.sub(pattern, replacer, content)


def load_env_file(env_path: Optional[str] = None) -> None:
    """Load environment variables from .env file."""
    from dotenv import load_dotenv
    
    if env_path:
        load_dotenv(env_path)
    else:
        # Try to find .env file in current directory, parents, and project root
        current_dir = Path.cwd()
        # Also check project root (where pyproject.toml lives)
        project_root = Path(__file__).parent.parent.parent
        for path in [current_dir, project_root] + list(current_dir.parents):
            env_file = path / ".env"
            if env_file.exists():
                load_dotenv(env_file)
                break


class LLMConfig(BaseModel):
    """LLM configuration."""

    provider: str = Field(default="openai", description="LLM Provider")
    model: str = Field(default="gpt-4", description="Model name")
    api_key: Optional[str] = Field(default=None, description="API key")
    base_url: Optional[str] = Field(default=None, description="Base URL")
    timeout: int = Field(default=60, ge=1, le=3600)
    max_retries: int = Field(default=3, ge=0, le=10)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: Optional[int] = Field(default=None, ge=1)

    model_config = {"env_prefix": "PY_LLM_"}

    def __init__(self, **data):
        import typing
        hints = {n: t for n, t in typing.get_type_hints(LLMConfig).items()}

        for field_name, field_type in hints.items():
            if field_name not in data or data[field_name] is None:
                env_name = f"PY_LLM_{field_name.upper()}"
                env_value = os.getenv(env_name)
                if env_value:
                    origin = getattr(field_type, "__origin__", None)
                    args = getattr(field_type, "__args__", ())
                    is_optional = origin is typing.Union and type(None) in args

                    if field_type is int or (is_optional and args[0] is int):
                        try:
                            data[field_name] = int(env_value)
                        except ValueError:
                            pass
                    elif field_type is float or (is_optional and args[0] is float):
                        try:
                            data[field_name] = float(env_value)
                        except ValueError:
                            pass
                    elif field_type is bool or (is_optional and args[0] is bool):
                        data[field_name] = env_value.lower() in ("true", "1", "yes", "on")
                    else:
                        data[field_name] = env_value
        super().__init__(**data)


class ToolConfig(BaseModel):
    """Tool configuration."""
    
    enabled: List[str] = Field(default_factory=list)
    disabled: List[str] = Field(default_factory=list)
    timeout: int = Field(default=30)
    allow_bash: bool = Field(default=True)
    allow_file_write: bool = Field(default=True)
    allowed_paths: List[str] = Field(default_factory=list)
    blocked_paths: List[str] = Field(default_factory=list)
    
    @field_validator("allowed_paths", "blocked_paths", mode="before")
    @classmethod
    def expand_paths(cls, v: List[str]) -> List[str]:
        """Expand user paths."""
        return [str(Path(p).expanduser().resolve()) for p in v]


class UIConfig(BaseModel):
    """UI configuration."""
    
    theme: str = Field(default="dark")
    show_tool_calls: bool = Field(default=True)
    show_thinking: bool = Field(default=False)
    stream_output: bool = Field(default=True)
    auto_suggest: bool = Field(default=True)
    history_size: int = Field(default=1000)


class PluginConfig(BaseModel):
    """Plugin system configuration."""

    enabled: List[str] = Field(default_factory=list)
    disabled: List[str] = Field(default_factory=list)

    #: Per-hook timeout in seconds. 0 = no timeout (use with caution).
    hook_timeout: float = Field(default=5.0, ge=0.0, le=300.0)

    #: Plugin is unhealthy when failure_count >= this.
    failure_threshold: int = Field(default=3, ge=1, le=100)

    #: Plugin is auto-disabled when failure_count >= this.
    disable_threshold: int = Field(default=5, ge=1, le=1000)

    def is_enabled(self, plugin_name: str) -> bool:
        """Check if a plugin is enabled.

        Logic:
        - If `enabled` list is non-empty: only plugins in the list are enabled
        - If `disabled` list has the plugin: it's disabled
        - Otherwise: enabled
        """
        if self.enabled:
            return plugin_name in self.enabled
        return plugin_name not in self.disabled


class HeartbeatConfig(BaseModel):
    """Heartbeat configuration for master↔subagent message passing."""

    enabled: bool = Field(default=True)
    interval: int = Field(default=30, ge=1, le=600, description="Seconds between heartbeat pings")
    timeout: int = Field(default=90, ge=1, le=1800, description="Seconds to wait for heartbeat response before marking failed")


class ReActConfig(BaseModel):
    """ReAct (Reasoning + Acting) mode configuration."""

    enabled: bool = Field(default=False, description="Enable ReAct mode for structured reasoning before actions")
    max_turns: int = Field(default=50, ge=1, le=200, description="Max reasoning turns before giving up")


class WebChannelConfig(BaseModel):
    """Web channel configuration."""
    
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8080)
    api_keys: List[str] = Field(default_factory=list)
    require_auth: bool = Field(default=True)


class ChannelConfig(BaseModel):
    """Channel configuration."""
    
    web: Optional[WebChannelConfig] = Field(default=None)


class Config(BaseModel):
    """Main configuration."""
    
    llm: LLMConfig = Field(default_factory=LLMConfig)
    tools: ToolConfig = Field(default_factory=ToolConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    plugins: PluginConfig = Field(default_factory=PluginConfig)
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)
    react: ReActConfig = Field(default_factory=ReActConfig)
    channels: Optional[ChannelConfig] = Field(default=None)
    
    @classmethod
    def from_file(cls, path: str, load_env: bool = True) -> "Config":
        """Load configuration from file with optional .env support."""
        import yaml

        # Load .env file first if requested
        if load_env:
            load_env_file()

        config_path = Path(path).expanduser()
        if not config_path.exists():
            return cls()

        with open(config_path, "r", encoding="utf-8") as f:
            raw_content = f.read()

        # Expand ${VAR:-default} env-var substitution before YAML parsing
        expanded_content = _expand_env_vars_in_content(raw_content)
        data = yaml.safe_load(expanded_content)

        return cls(**data)
    
    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        # Load .env file first
        load_env_file()
        return cls()
