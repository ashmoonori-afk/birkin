"""Bounded redacted projection of canonical workspace records."""

from __future__ import annotations

from typing import cast

from birkin.web.browser_security import browser_privacy_filter
from birkin.workspace.records import WorkspaceEvent

_SENSITIVE_KEYS = {
    "api_key",
    "auth",
    "authorization",
    "bootstrap_secret",
    "cookie",
    "credential",
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
_PRIVACY_FILTER = browser_privacy_filter()


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


def _public_mapping(mapping: dict[str, object]) -> dict[str, object]:
    projected: dict[str, object] = {}
    for key, value in mapping.items():
        normalized = key.casefold()
        if normalized in _INTERNAL_KEYS:
            continue
        if normalized in _SENSITIVE_KEYS:
            projected[key] = "[REDACTED]"
        elif normalized in {"error", "message", "detail"} and isinstance(value, str):
            projected[key] = _public_error(value)
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
    return value


def _public_error(value: str) -> str:
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
    return _PRIVACY_FILTER.text(bounded, max_length=_MAX_ERROR_CHARS)
