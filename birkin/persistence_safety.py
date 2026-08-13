"""Mechanical safety checks for model-authored durable state."""

from __future__ import annotations

import re

from .transcripts import redact_text

_INJECTION_RE = re.compile(
    r"(?is)\b(?:ignore|disregard|override)\b.{0,80}"
    r"\b(?:previous|prior|system|developer)\b.{0,80}"
    r"\b(?:instruction|prompt|rule)s?\b"
)
_EXFILTRATION_RE = re.compile(
    r"(?is)\b(?:exfiltrat|upload|send|reveal|steal)\w*\b.{0,120}"
    r"(?:~/\.ssh|\.env\b|credential|password|secret|token|private key)"
)


def unsafe_persistence_reason(*values: object) -> str | None:
    """Return why model-authored text is unsafe to persist, if applicable."""
    text = "\n".join(str(value or "") for value in values)
    if redact_text(text) != text:
        return "contains a secret or prompt-injection instruction"
    if _INJECTION_RE.search(text) or _EXFILTRATION_RE.search(text):
        return "contains a secret or prompt-injection instruction"
    return None
