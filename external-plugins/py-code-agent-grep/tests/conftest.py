"""Shared test fixtures for GrepPlugin tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def sample_project(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text(
        "def hello():\n    print('hello')\n\ndef world():\n    print('world')\n"
    )
    (tmp_path / "src" / "utils.py").write_text(
        "def helper():\n    # TODO: refactor this\n    pass\n"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text(
        "def test_hello():\n    assert hello() == 'hello'\n"
    )
    (tmp_path / ".git").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "README.md").write_text("# Project\n\nTODO: write docs\n")
    return tmp_path


@pytest.fixture
def ts_project(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "api.ts").write_text(
        "async function fetchData(url: string) {\n"
        "    const res = await fetch(url, { method: 'GET' });\n"
        "    return res.json();\n"
        "}\n"
        "\n"
        "async function postData(url: string, data: any) {\n"
        "    const res = await fetch(url, {\n"
        "        method: 'POST',\n"
        "        body: JSON.stringify(data),\n"
        "    });\n"
        "    return res.json();\n"
        "}\n"
    )
    (tmp_path / "src" / "index.ts").write_text("export { fetchData, postData };\n")
    return tmp_path
