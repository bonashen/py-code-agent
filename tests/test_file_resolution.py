"""Test file resolution priority for skills, soul, and agent files."""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
import importlib.util

import pytest

_repo_root = Path(__file__).parent.parent
_plugins_samples = _repo_root / "plugins" / "samples"


def _load_plugin(name: str):
    spec = importlib.util.spec_from_file_location(name, _plugins_samples / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


skills_mod = _load_plugin("skills_plugin")
_discover_skills = skills_mod._discover_skills
_load_skill_file = skills_mod._load_skill_file

soul_mod = _load_plugin("soul_plugin")
SoulPlugin = soul_mod.SoulPlugin

agent_mod = _load_plugin("agent_identity_plugin")
AgentIdentityPlugin = agent_mod.AgentIdentityPlugin


class TestSkillsResolution:
    """Test skills file resolution order: local > global > home."""

    def test_first_found_wins(self, monkeypatch):
        """No chdir → searches from cwd; local path won't be found → falls through to home."""
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            home.mkdir(parents=True)
            (home / ".claude" / "skills" / "test-skill").mkdir(parents=True, exist_ok=True)
            (home / ".claude" / "skills" / "test-skill" / "SKILL.md").write_text("# Home")

            monkeypatch.setenv("HOME", str(home))
            # Use module loaded at test-file level, clear its cache
            skills_mod.SKILL_CACHE.clear()
            skills = skills_mod._discover_skills()
            assert skills["test-skill"]["content"] == "# Home"

    def test_local_overrides_global(self, monkeypatch):
        """chdir to local dir → local path found → wins."""
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            local = Path(tmpdir) / "local"
            home.mkdir(parents=True)
            local.mkdir(parents=True)

            # local: ./.py-code-agent/skills/
            (local / ".py-code-agent" / "skills" / "my-skill").mkdir(parents=True, exist_ok=True)
            (local / ".py-code-agent" / "skills" / "my-skill" / "SKILL.md").write_text("# LOCAL")
            # home: ~/.claude/skills/
            (home / ".claude" / "skills" / "my-skill").mkdir(parents=True, exist_ok=True)
            (home / ".claude" / "skills" / "my-skill" / "SKILL.md").write_text("# HOME")

            monkeypatch.setenv("HOME", str(home))
            monkeypatch.chdir(local)
            skills_mod.SKILL_CACHE.clear()
            skills = skills_mod._discover_skills()
            assert skills["my-skill"]["content"] == "# LOCAL"

    def test_global_overrides_home(self, monkeypatch):
        """chdir to local (but no local skills dir) → global ~/.config/ wins over ~/.claude/."""
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            local = Path(tmpdir) / "local"
            home.mkdir(parents=True)
            local.mkdir(parents=True)

            # global: ~/.config/py-code-agent/skills/
            (home / ".config" / "py-code-agent" / "skills" / "skill2").mkdir(parents=True, exist_ok=True)
            (home / ".config" / "py-code-agent" / "skills" / "skill2" / "SKILL.md").write_text("# CONFIG")
            # home: ~/.claude/skills/
            (home / ".claude" / "skills" / "skill2").mkdir(parents=True, exist_ok=True)
            (home / ".claude" / "skills" / "skill2" / "SKILL.md").write_text("# HOME")

            monkeypatch.setenv("HOME", str(home))
            monkeypatch.chdir(local)
            skills_mod.SKILL_CACHE.clear()
            skills = skills_mod._discover_skills()
            assert skills["skill2"]["content"] == "# CONFIG"

    def test_home_fallback(self, monkeypatch):
        """No local, no global → home ~/.claude/skills/ used."""
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            home.mkdir(parents=True)
            (home / ".claude" / "skills" / "fallback-skill").mkdir(parents=True, exist_ok=True)
            (home / ".claude" / "skills" / "fallback-skill" / "SKILL.md").write_text("# HOME ONLY")

            monkeypatch.setenv("HOME", str(home))
            skills_mod.SKILL_CACHE.clear()
            skills = skills_mod._discover_skills()
            assert skills["fallback-skill"]["content"] == "# HOME ONLY"

    def test_same_name_not_duplicated(self, monkeypatch):
        """Same skill name in global and home → deduplicated (first found wins)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            home.mkdir(parents=True)

            (home / ".config" / "py-code-agent" / "skills" / "dup").mkdir(parents=True, exist_ok=True)
            (home / ".config" / "py-code-agent" / "skills" / "dup" / "SKILL.md").write_text("# CONFIG")
            (home / ".claude" / "skills" / "dup").mkdir(parents=True, exist_ok=True)
            (home / ".claude" / "skills" / "dup" / "SKILL.md").write_text("# HOME")

            monkeypatch.setenv("HOME", str(home))
            skills_mod.SKILL_CACHE.clear()
            skills = skills_mod._discover_skills()
            # global (~/.config/) is searched before home (~/.claude/), so CONFIG wins
            assert len(skills) == 1
            assert skills["dup"]["content"] == "# CONFIG"


class TestSoulResolution:
    """Test soul.md resolution order: local > global > home."""

    def test_local_priority(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            local = Path(tmpdir) / "local"
            home.mkdir(parents=True)
            local.mkdir(parents=True)

            (home / ".claude").mkdir(parents=True, exist_ok=True)
            (local / ".py-code-agent").mkdir(parents=True, exist_ok=True)
            (home / ".claude" / "soul.md").write_text("# HOME SOUL")
            (local / ".py-code-agent" / "soul.md").write_text("# LOCAL SOUL")

            monkeypatch.setenv("HOME", str(home))
            monkeypatch.chdir(local)
            plugin = SoulPlugin()
            assert plugin.get_soul() == "# LOCAL SOUL"

    def test_global_priority(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            home.mkdir(parents=True)

            (home / ".claude").mkdir(parents=True, exist_ok=True)
            (home / ".config" / "py-code-agent").mkdir(parents=True, exist_ok=True)
            (home / ".claude" / "soul.md").write_text("# HOME")
            (home / ".config" / "py-code-agent" / "soul.md").write_text("# CONFIG")

            monkeypatch.setenv("HOME", str(home))
            monkeypatch.chdir(home)
            plugin = SoulPlugin()
            assert plugin.get_soul() == "# CONFIG"

    def test_falls_back_to_default(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            home.mkdir(parents=True)

            monkeypatch.setenv("HOME", str(home))
            monkeypatch.chdir(home)
            plugin = SoulPlugin()
            content = plugin.get_soul()
            assert "# Soul" in content


class TestAgentIdentityResolution:
    """Test agent.md resolution order: local > global > home."""

    def test_local_priority(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            local = Path(tmpdir) / "local"
            home.mkdir(parents=True)
            local.mkdir(parents=True)

            (home / ".claude").mkdir(parents=True, exist_ok=True)
            (local / ".py-code-agent").mkdir(parents=True, exist_ok=True)
            (home / ".claude" / "agent.md").write_text("# HOME AGENT")
            (local / ".py-code-agent" / "agent.md").write_text("# LOCAL AGENT")

            monkeypatch.setenv("HOME", str(home))
            monkeypatch.chdir(local)
            plugin = AgentIdentityPlugin()
            assert plugin.get_identity_content() == "# LOCAL AGENT"

    def test_global_priority(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            home.mkdir(parents=True)

            (home / ".claude").mkdir(parents=True, exist_ok=True)
            (home / ".config" / "py-code-agent").mkdir(parents=True, exist_ok=True)
            (home / ".claude" / "agent.md").write_text("# HOME")
            (home / ".config" / "py-code-agent" / "agent.md").write_text("# CONFIG")

            monkeypatch.setenv("HOME", str(home))
            monkeypatch.chdir(home)
            plugin = AgentIdentityPlugin()
            assert plugin.get_identity_content() == "# CONFIG"
