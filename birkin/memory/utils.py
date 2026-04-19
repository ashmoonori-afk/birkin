"""Shared utilities for the memory subsystem."""

from __future__ import annotations


def strip_frontmatter(content: str) -> str:
    """Remove YAML frontmatter (---...---) from wiki page content."""
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return content
