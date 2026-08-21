"""Bounded redacted projection of canonical workspace records."""

from __future__ import annotations

import re
from typing import cast

from birkin.web.browser_security import browser_privacy_filter
from birkin.workspace.contracts import REDACTION_MARKER
from birkin.workspace.records import WorkspaceEvent

_SENSITIVE_KEYS = {
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
}
_INTERNAL_KEYS = {
    "fingerprint",
}
_TERMINAL_INPUT_SAFE_KEYS = {
    "sequence",
    "terminal_id",
}
_MAX_ERROR_CHARS = 300
_MAX_PUBLIC_TEXT = 20_000
_PRIVACY_FILTER = browser_privacy_filter()
_SECRET_TEXT = re.compile(
    r"(?i)\b(?:bearer\s+\S+|seeded[_-][A-Za-z0-9_-]+|"
    + r"(?:sk|ghp|github_pat|xox[baprs])[-_][A-Za-z0-9_-]{8,})"
)


def public_workspace_event(event: WorkspaceEvent) -> dict[str, object]:
    """Return an event safe for the native projection boundary."""

    projected = event.to_json()
    if event.type == "terminal.input":
        payload = {
            key: event.payload[key]
            for key in _TERMINAL_INPUT_SAFE_KEYS
            if key in event.payload
        }
        payload["redacted"] = True
        projected["payload"] = payload
        return projected
    projected["payload"] = _public_mapping(event.payload)
    return projected


def public_native_mapping(
    mapping: dict[str, object],
) -> dict[str, object]:
    """Recursively redact a native-facing record at the process boundary."""

    return _public_mapping(mapping)


def _public_mapping(mapping: dict[str, object]) -> dict[str, object]:
    projected: dict[str, object] = {}
    for key, value in mapping.items():
        normalized = key.casefold()
        if normalized in _INTERNAL_KEYS:
            continue
        if normalized in _SENSITIVE_KEYS:
            # An absent secret stays absent: null means "no authority here",
            # while the marker means "authority exists and is withheld".
            projected[key] = None if value is None else REDACTION_MARKER
        elif normalized in {"error", "message", "detail"} and isinstance(value, str):
            projected[key] = public_error_text(value)
        else:
            projected[key] = _public_value(value)
    return projected


def _public_value(value: object) -> object:
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        string_mapping = {
            key: item
            for key, item in mapping.items()
            if isinstance(key, str)
        }
        return _public_mapping(string_mapping)
    if isinstance(value, list):
        return [_public_value(item) for item in cast(list[object], value)]
    if isinstance(value, str):
        return _public_text(value)
    return value


def public_error_text(value: str) -> str:
    """Return bounded diagnostic text without traceback or secret lines."""

    lines: list[str] = []
    for line in value.splitlines():
        if line.startswith(("Traceback", "  File ")):
            continue
        normalized = line.casefold()
        if any(f"{key}=" in normalized for key in _SENSITIVE_KEYS):
            lines.append("[REDACTED]")
        else:
            lines.append(line)
    bounded = "\n".join(lines)
    return _public_text(bounded)[:_MAX_ERROR_CHARS]


def _public_text(value: str) -> str:
    redacted = _SECRET_TEXT.sub("[REDACTED]", value)
    return _PRIVACY_FILTER.text(redacted, max_length=_MAX_PUBLIC_TEXT)
