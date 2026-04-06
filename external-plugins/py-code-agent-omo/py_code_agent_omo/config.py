"""OMO plugin configuration loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


class OmoConfig:
    """Loads and manages OMO configuration from YAML files.

    Search order:
    1. ./.py-code-agent/omo.yaml (project-local)
    2. ~/.config/py-code-agent/omo.yaml (global user config)
    """

    DEFAULT_CATEGORIES = {
        "visual-engineering": {"model": "google/gemini-3.1-pro", "variant": "high"},
        "ultrabrain": {"model": "openai/gpt-5.4", "variant": "xhigh"},
        "deep": {"model": "anthropic/claude-opus-4-6"},
        "quick": {"model": "openai/gpt-5.4-mini"},
        "artistry": {"model": "anthropic/claude-sonnet-4-6"},
        "unspecified-high": {"model": "anthropic/claude-opus-4-6"},
        "unspecified-low": {"model": "openai/gpt-5.4-mini"},
        "writing": {"model": "anthropic/claude-sonnet-4-6"},
    }

    DEFAULT_AGENTS = {
        "oracle": {"model": "openai/gpt-5.4", "variant": "high"},
        "librarian": {"model": "anthropic/claude-sonnet-4-6"},
        "explore": {"model": "xai/grok-code-fast-1"},
        "frontend-engineer": {"model": "google/gemini-3.1-pro"},
    }

    DEFAULT_FALLBACKS = {
        "anthropic": ["openai", "google"],
        "openai": ["anthropic", "google"],
        "google": ["anthropic", "openai"],
    }

    def __init__(self) -> None:
        self._raw: Dict[str, Any] = {}
        self._categories: Dict[str, Dict[str, str]] = dict(self.DEFAULT_CATEGORIES)
        self._agents: Dict[str, Dict[str, str]] = dict(self.DEFAULT_AGENTS)
        self._fallbacks: Dict[str, List[str]] = dict(self.DEFAULT_FALLBACKS)
        self._intent_gate: Dict[str, Any] = {
            "enabled": True,
            "model": "openai/gpt-5.4-mini",
            "threshold": 0.7,
        }
        self._subagent: Dict[str, Any] = {
            "enabled": True,
            "max_concurrent": 4,
            "default_timeout": 300,
        }
        self._discipline: Dict[str, Any] = {
            "enabled": True,
            "ralph_loop": {"enabled": True, "max_iterations": 10},
            "comment_checker": {"enabled": True, "max_comment_ratio": 0.15},
        }
        self._loaded = False

    def load(self) -> None:
        """Load configuration from YAML files."""
        if self._loaded:
            return

        config_paths = [
            Path(".py-code-agent/omo.yaml"),
            Path.home() / ".config" / "py-code-agent" / "omo.yaml",
        ]

        for p in config_paths:
            if p.exists():
                try:
                    with open(p, encoding="utf-8") as f:
                        self._raw = yaml.safe_load(f) or {}
                    self._merge()
                except Exception:
                    pass
                break

        self._loaded = True

    def _merge(self) -> None:
        """Merge loaded config with defaults."""
        cr = self._raw.get("category_router", {})
        if cr.get("categories"):
            self._categories.update(cr["categories"])
        if cr.get("agents"):
            self._agents.update(cr["agents"])
        if cr.get("provider_fallbacks"):
            self._fallbacks.update(cr["provider_fallbacks"])

        ig = self._raw.get("intent_gate", {})
        if ig:
            self._intent_gate.update(ig)

        sa = self._raw.get("subagent", {})
        if sa:
            self._subagent.update(sa)

        disc = self._raw.get("discipline", {})
        if disc:
            self._discipline.update(disc)

    @property
    def categories(self) -> Dict[str, Dict[str, str]]:
        self.load()
        return self._categories

    @property
    def agents(self) -> Dict[str, Dict[str, str]]:
        self.load()
        return self._agents

    @property
    def fallbacks(self) -> Dict[str, List[str]]:
        self.load()
        return self._fallbacks

    @property
    def intent_gate(self) -> Dict[str, Any]:
        self.load()
        return self._intent_gate

    @property
    def subagent(self) -> Dict[str, Any]:
        self.load()
        return self._subagent

    @property
    def discipline(self) -> Dict[str, Any]:
        self.load()
        return self._discipline

    def get_category(self, category: str) -> Dict[str, str]:
        """Resolve category to model config."""
        self.load()
        if category in self._categories:
            return self._categories[category]
        # Alias mapping
        aliases = {
            "visual": "visual-engineering",
            "frontend": "visual-engineering",
            "ui": "visual-engineering",
            "ux": "visual-engineering",
            "design": "visual-engineering",
            "brain": "ultrabrain",
            "logic": "ultrabrain",
            "arch": "ultrabrain",
        }
        alias = aliases.get(category)
        if alias and alias in self._categories:
            return self._categories[alias]
        return self._categories.get("unspecified-low", {"model": "openai/gpt-5.4-mini"})

    def get_agent(self, agent_name: str) -> Dict[str, str]:
        """Resolve agent name to model config."""
        self.load()
        return self._agents.get(
            agent_name, self._agents.get("librarian", {"model": "anthropic/claude-sonnet-4.6"})
        )

    def resolve_with_fallback(self, model: str) -> str:
        """If primary model unavailable, try fallback providers."""
        provider = model.split("/")[0] if "/" in model else "openai"
        fallbacks = self._fallbacks.get(provider, [])
        # In production, check actual provider availability via LLM provider
        return model


# Singleton
_omo_config: Optional[OmoConfig] = None


def get_omo_config() -> OmoConfig:
    """Get the global OMO config singleton."""
    global _omo_config
    if _omo_config is None:
        _omo_config = OmoConfig()
    return _omo_config
