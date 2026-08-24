"""Bounded JSON values for Birkin's local native protocol."""

from __future__ import annotations

import math
import re
from typing import NoReturn, TypeAlias, cast

MAX_JSON_DEPTH = 12

JSONValue: TypeAlias = (
    None
    | bool
    | int
    | float
    | str
    | list["JSONValue"]
    | dict[str, "JSONValue"]
)

_IDENTIFIER = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1


class NativeProtocolError(ValueError):
    """A bounded protocol refusal with a stable public code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code: str = code


def object_mapping(raw: object, label: str) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise NativeProtocolError("E_JSON", f"{label} must be a JSON object")
    mapping = cast(dict[object, object], raw)
    if not all(isinstance(key, str) for key in mapping):
        raise NativeProtocolError("E_JSON", f"{label} must be a JSON object")
    return cast(dict[str, object], mapping)


def identifier(raw: object, label: str) -> str:
    if not isinstance(raw, str) or _IDENTIFIER.fullmatch(raw) is None:
        raise NativeProtocolError(
            "E_IDENTIFIER",
            f"{label} must be a bounded identifier",
        )
    return raw


def json_object(raw: object, *, depth: int) -> dict[str, JSONValue]:
    if not isinstance(raw, dict):
        raise NativeProtocolError("E_JSON", "body must be a JSON object")
    mapping = cast(dict[object, object], raw)
    if not all(isinstance(key, str) for key in mapping):
        raise NativeProtocolError("E_JSON", "body must be a JSON object")
    if depth > MAX_JSON_DEPTH:
        raise NativeProtocolError("E_JSON_DEPTH", "JSON exceeds maximum depth")
    result: dict[str, JSONValue] = {}
    for key, value in mapping.items():
        normalized_key = _json_string(cast(str, key))
        if normalized_key in result:
            raise NativeProtocolError(
                "E_DUPLICATE_KEY",
                "JSON object contains a duplicate key",
            )
        result[normalized_key] = _json_value(value, depth=depth + 1)
    return result


def _json_value(raw: object, *, depth: int) -> JSONValue:
    if depth > MAX_JSON_DEPTH:
        raise NativeProtocolError("E_JSON_DEPTH", "JSON exceeds maximum depth")
    if isinstance(raw, float) and not math.isfinite(raw):
        raise NativeProtocolError(
            "E_NONFINITE_NUMBER",
            "body contains a non-finite number",
        )
    if isinstance(raw, int) and not isinstance(raw, bool):
        if raw < _INT64_MIN or raw > _INT64_MAX:
            raise NativeProtocolError(
                "E_JSON",
                "integer is outside the supported range",
            )
        return raw
    if isinstance(raw, str):
        return _json_string(raw)
    if raw is None or isinstance(raw, bool | float):
        return raw
    if isinstance(raw, list):
        values = cast(list[object], raw)
        return [_json_value(value, depth=depth + 1) for value in values]
    if isinstance(raw, dict):
        return json_object(cast(object, raw), depth=depth)
    raise NativeProtocolError("E_JSON", "body contains a non-JSON value")


def _json_string(value: str) -> str:
    try:
        return value.encode("utf-16-le", errors="surrogatepass").decode("utf-16-le")
    except UnicodeDecodeError as exc:
        raise NativeProtocolError(
            "E_JSON",
            "JSON contains an unpaired surrogate",
        ) from exc


def strict_object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    mapping: dict[str, object] = {}
    for key, value in pairs:
        if key in mapping:
            raise NativeProtocolError(
                "E_DUPLICATE_KEY",
                "JSON object contains a duplicate key",
            )
        mapping[key] = value
    return mapping


def reject_nonfinite(_value: str) -> NoReturn:
    raise NativeProtocolError(
        "E_NONFINITE_NUMBER",
        "JSON contains a non-finite number",
    )
