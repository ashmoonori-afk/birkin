"""Safe deterministic serialization for untrusted Office artifact evidence."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TypeAlias, cast

from typing_extensions import override

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

_REDACTED = "[redacted]"
@dataclass(frozen=True, slots=True)
class IntegritySerializationError(TypeError):
    """A proposal contains a value outside the exact JSON data model."""

    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\b(?:gh[opusr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{16,})\b"),
    re.compile(
        r"(?i)(\b(?:api[_-]?key|password|passwd|secret|token)\b\s*[:=]\s*)"
        + r"([^\s,;]+)"
    ),
)


def escape_controls(text: str) -> str:
    """Render terminal/control characters visibly without normalizing text."""
    rendered: list[str] = []
    for character in text:
        category = unicodedata.category(character)
        if category in {"Cc", "Cf", "Cs"}:
            rendered.append(f"\\u{ord(character):04x}")
        else:
            rendered.append(character)
    return "".join(rendered)


def redact_text(text: str, secrets: Iterable[str] = ()) -> str:
    """Redact explicit configured values and common credential shapes."""
    redacted = text
    for secret in sorted({item for item in secrets if item}, key=len, reverse=True):
        redacted = redacted.replace(secret, _REDACTED)
    for pattern in _SECRET_PATTERNS:
        if pattern.groups:
            redacted = pattern.sub(lambda match: f"{match.group(1)}{_REDACTED}", redacted)
        else:
            redacted = pattern.sub(_REDACTED, redacted)
    return escape_controls(redacted)


def sanitize_data(value: object, *, secrets: Iterable[str] = ()) -> JsonValue:
    """Copy JSON-shaped evidence while keeping every untrusted string as data."""
    configured = tuple(secrets)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return redact_text(value, configured)
    if isinstance(value, Mapping):
        result: dict[str, JsonValue] = {}
        mapping = cast("Mapping[object, object]", value)
        for key, item in mapping.items():
            safe_key = redact_text(str(key), configured)
            result[safe_key] = sanitize_data(item, secrets=configured)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [sanitize_data(item, secrets=configured) for item in value]
    return redact_text(str(value), configured)


def canonical_json(value: object, *, secrets: Iterable[str] = ()) -> str:
    """Serialize sanitized evidence canonically; controls remain escaped."""
    safe = sanitize_data(value, secrets=secrets)
    return json.dumps(
        safe,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _integrity_value(value: object, active: set[int]) -> JsonValue:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise IntegritySerializationError("integrity JSON numbers must be finite")
        return value
    identity = id(value)
    if identity in active:
        raise IntegritySerializationError("integrity JSON must not contain cycles")
    if isinstance(value, Mapping):
        active.add(identity)
        try:
            result: dict[str, JsonValue] = {}
            for key, item in cast("Mapping[object, object]", value).items():
                if not isinstance(key, str):
                    raise IntegritySerializationError(
                        "integrity JSON object keys must be strings"
                    )
                result[key] = _integrity_value(item, active)
            return result
        finally:
            active.remove(identity)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        active.add(identity)
        try:
            return [_integrity_value(item, active) for item in value]
        finally:
            active.remove(identity)
    raise IntegritySerializationError("integrity authority must contain only JSON values")


def canonical_integrity_json(value: object) -> str:
    """Serialize exact JSON authority without redaction or lossy coercion."""
    exact = _integrity_value(value, set())
    return json.dumps(
        exact,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
