"""Auto engine selection logic based on pattern analysis."""

from __future__ import annotations

import re
from typing import Optional


class EngineRouter:
    """Automatically selects the best search engine based on pattern analysis.

    Decision rules (evaluated in order):
    1. Contains meta-variables ($VAR, $$$) → AST
    2. Explicit lang specified → AST
    3. Include pattern targets non-code files → TEXT
    4. Pattern matches comment/string hints → TEXT
    5. Default → TEXT (faster, more universal)
    """

    AST_META_PATTERN = re.compile(r"\$[A-Z_][A-Z_0-9]*|\$\$\$")

    TEXT_HINTS = [
        r"TODO|FIXME|HACK|XXX",
        r"#.*|//.*|/\*.*",
        r'["\'].*["\']',
    ]

    @classmethod
    def select(
        cls,
        pattern: str,
        lang: Optional[str] = None,
        include: str = "*",
    ) -> str:
        if cls.AST_META_PATTERN.search(pattern):
            return "ast"

        if lang is not None:
            return "ast"

        non_code_patterns = ["*.md", "*.txt", "*.log", "*.csv", "*.xml"]
        for nc_pattern in non_code_patterns:
            if include == nc_pattern or nc_pattern in include:
                return "text"

        for hint in cls.TEXT_HINTS:
            if re.search(hint, pattern, re.IGNORECASE):
                return "text"

        return "text"
