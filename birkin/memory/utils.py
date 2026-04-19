"""Shared utilities for the memory subsystem."""

from __future__ import annotations

import re


def strip_frontmatter(content: str) -> str:
    """Remove YAML frontmatter (---...---) from wiki page content."""
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return content


# Regex patterns for prompt injection detection
_INJECTION_RE = [
    re.compile(r"(?i)\[?\s*system\s*\]"),
    re.compile(r"(?i)you\s+are\s+now\b"),
    re.compile(r"(?i)ignore\s+(all\s+)?previous"),
    re.compile(r"(?i)forget\s+(all\s+)?previous"),
    re.compile(r"(?i)new\s+instructions?\s*:"),
    re.compile(r"(?i)override\s+(system|instructions?)"),
    re.compile(r"(?i)<\s*system\s*>"),
    re.compile(r"(?i)<<\s*SYS\s*>>"),
    re.compile(r"(?i)disregard\s+(all\s+)?(previous|above)"),
]


def sanitize_content(content: str) -> tuple[str, list[str]]:
    """Detect and neutralize prompt injection patterns.

    Wraps suspicious patterns in inline code blocks. Skips fenced
    code blocks to avoid false positives on technical docs.

    Returns (sanitized_content, list_of_warning_strings).
    """
    warnings: list[str] = []
    parts = re.split(r"(```[\s\S]*?```)", content)
    for i, part in enumerate(parts):
        if part.startswith("```"):
            continue
        for pattern in _INJECTION_RE:
            for match in pattern.finditer(part):
                matched = match.group()
                warnings.append(f"Neutralized: {matched!r}")
                part = part.replace(matched, f"`{matched}`", 1)
        parts[i] = part
    return "".join(parts), warnings
