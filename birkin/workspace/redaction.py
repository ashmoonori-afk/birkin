"""Bounded, secret-free text for anything that becomes durable or public."""

from __future__ import annotations

import re

REDACTION_TEXT = "[REDACTED]"
MAX_ERROR_CHARS = 300

SENSITIVE_KEYS = frozenset({
    "api_key",
    "auth",
    "authorization",
    "bootstrap_secret",
    "cookie",
    "credential",
    "lease",
    "password",
    "provider_token",
    "secret",
    "session_capability",
    "token",
})

SECRET_TEXT = re.compile(
    r"(?i)\b(?:bearer\s+\S+|seeded[_-][A-Za-z0-9_-]+|"
    + r"(?:sk|ghp|github_pat|xox[baprs])[-_][A-Za-z0-9_-]{8,})"
)


def redact_secrets(value: str) -> str:
    """Replace anything shaped like a credential wherever it appears."""
    return SECRET_TEXT.sub(REDACTION_TEXT, value)


def bounded_error_text(value: str) -> str:
    """Return diagnostic text with no traceback, no credential, and a bound.

    Applied before error text becomes durable or crosses a process boundary.
    An exception message is attacker- and upstream-influenced, so it is
    treated as untrusted content rather than as a developer string.
    """
    lines: list[str] = []
    for line in value.splitlines():
        if line.startswith(("Traceback", "  File ")):
            continue
        normalized = line.casefold()
        if any(f"{key}=" in normalized for key in SENSITIVE_KEYS):
            lines.append(REDACTION_TEXT)
        else:
            lines.append(redact_secrets(line))
    return "\n".join(lines)[:MAX_ERROR_CHARS]
