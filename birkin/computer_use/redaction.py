"""Bounded secret and PII redaction at evidence boundaries."""

from __future__ import annotations

import re

_EMAIL = re.compile(
    r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?![\w.-])",
    re.IGNORECASE,
)
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE)
_API_KEY = re.compile(
    r"\b(?:sk|pk|api|token)[-_][A-Za-z0-9_-]{12,}\b",
    re.IGNORECASE,
)
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")


def redact_text(value: str, *, max_chars: int = 4096) -> str:
    """Redact common secret/PII forms and bound retained text."""
    redacted = _BEARER.sub("[REDACTED_SECRET]", value)
    redacted = _API_KEY.sub("[REDACTED_SECRET]", redacted)
    redacted = _EMAIL.sub("[REDACTED_EMAIL]", redacted)
    redacted = _CARD.sub("[REDACTED_PAYMENT]", redacted)
    if len(redacted) <= max_chars:
        return redacted
    return redacted[:max_chars] + "[TRUNCATED]"
