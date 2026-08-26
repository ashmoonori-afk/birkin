"""Bounded redacted projection of canonical workspace records."""

from __future__ import annotations

from typing import cast

from birkin.web.browser_security import browser_privacy_filter
from birkin.workspace.contracts import REDACTION_MARKER
from birkin.workspace.records import WorkspaceEvent
from birkin.workspace.redaction import (
    MAX_ERROR_CHARS,
    SENSITIVE_KEYS,
    bounded_error_text,
    redact_secrets,
)

_SENSITIVE_KEYS = SENSITIVE_KEYS
_INTERNAL_KEYS = {
    "fingerprint",
}
_TERMINAL_INPUT_SAFE_KEYS = {
    "sequence",
    "terminal_id",
}
_MAX_PUBLIC_TEXT = 20_000
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
    if event.type == "terminal.output":
        projected["payload"] = _public_terminal_output_payload(event.payload)
        return projected
    projected["payload"] = _public_mapping(event.payload)
    return projected


def _public_terminal_output_payload(payload: dict[str, object]) -> dict[str, object]:
    projected: dict[str, object] = {}
    terminal_id = payload.get("terminal_id")
    sequence = payload.get("sequence")
    data = payload.get("data")
    if isinstance(terminal_id, str):
        projected["terminal_id"] = terminal_id
    if type(sequence) is int:
        projected["sequence"] = sequence
    if isinstance(data, str):
        projected["data"] = redact_secrets(data)[:_MAX_PUBLIC_TEXT]
    return projected


def public_workspace_snapshot(mapping: dict[str, object]) -> dict[str, object]:
    """Project a snapshot while preserving bounded terminal VT screens."""

    projected = _public_mapping(mapping)
    source_terminals = mapping.get("terminals")
    public_terminals = projected.get("terminals")
    if isinstance(source_terminals, list) and isinstance(public_terminals, list):
        source_values = cast(list[object], source_terminals)
        public_values = cast(list[object], public_terminals)
        for index, source_terminal in enumerate(source_values):
            if index >= len(public_values):
                break
            public_terminal = public_values[index]
            if not isinstance(source_terminal, dict) or not isinstance(public_terminal, dict):
                continue
            source_mapping = cast(dict[object, object], source_terminal)
            public_mapping = cast(dict[object, object], public_terminal)
            screen = source_mapping.get("screen")
            if not isinstance(screen, str):
                continue
            bounded = redact_secrets(screen)[-65_536:]
            if bounded and 0xDC00 <= ord(bounded[0]) <= 0xDFFF:
                bounded = bounded[1:]
            public_mapping["screen"] = bounded
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

    return _public_text(bounded_error_text(value))[:MAX_ERROR_CHARS]


def _public_text(value: str) -> str:
    return _PRIVACY_FILTER.text(
        redact_secrets(value),
        max_length=_MAX_PUBLIC_TEXT,
    )
