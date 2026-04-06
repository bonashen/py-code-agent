"""Pytest configuration — sets environment variables before any imports."""

import os
import sys

import pytest

# Prevent LiteLLM from making blocking network requests during import.
# It tries to fetch https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json
# which can hang indefinitely if the network is unavailable.
os.environ.setdefault("LITELLM_SUPPRESS_DEBUG_INFO", "True")
os.environ.setdefault("LITELLM_NO_CACHE", "True")
os.environ.setdefault("LITELLM_DROP_PARAMS", "True")
os.environ.setdefault("LITELLM_FALLBACK_LOCALLY", "True")
os.environ.setdefault("HTTP_TIMEOUT", "5")
os.environ.setdefault("HTTPS_TIMEOUT", "5")


@pytest.fixture(autouse=True)
def clear_skills_cache():
    """Clear SKILL_CACHE between tests to prevent state leakage.

    Uses sys.modules to access SKILL_CACHE without triggering the full
    plugin import chain (which takes ~30s due to litellm initialization).
    """
    # Access via sys.modules to avoid triggering litellm import.
    mod = sys.modules.get("plugins.builtin.skills_plugin")
    if mod is not None and hasattr(mod, "SKILL_CACHE"):
        mod.SKILL_CACHE.clear()
    yield
    if mod is not None and hasattr(mod, "SKILL_CACHE"):
        mod.SKILL_CACHE.clear()
