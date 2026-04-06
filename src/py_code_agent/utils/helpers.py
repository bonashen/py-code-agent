"""Utility helpers."""

import re
import time
import uuid
from datetime import datetime
from typing import Optional


def generate_id() -> str:
    """Generate a unique ID."""
    return str(uuid.uuid4())


def format_timestamp(timestamp: Optional[float] = None) -> str:
    """Format timestamp as ISO 8601 string."""
    if timestamp is None:
        timestamp = time.time()
    return datetime.fromtimestamp(timestamp).isoformat()


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to be safe for filesystem."""
    # Replace invalid characters
    filename = re.sub(r'[<>:"/\\|?*]', "_", filename)
    # Remove leading/trailing dots and spaces
    filename = filename.strip(". ")
    # Limit length
    if len(filename) > 255:
        filename = filename[:255]
    return filename or "untitled"


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """Truncate text to max length."""
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def count_tokens(text: str, approx_chars_per_token: int = 4) -> int:
    """Approximate token count."""
    return len(text) // approx_chars_per_token
