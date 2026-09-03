"""Canonical JSON and boundary parsing for approval execution journals."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Protocol, TypeAlias, TypeVar

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]
_CanonicalValue = TypeVar("_CanonicalValue")


class _JsonLoader(Protocol):
    def __call__(self, s: str) -> JSONValue: ...


_load_json: _JsonLoader = json.loads


class JournalCodecError(RuntimeError):
    """A journal line is not canonical JSON-compatible data."""


def canonical(value: Mapping[str, _CanonicalValue]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def parse_mapping(value: JSONValue) -> dict[str, JSONValue]:
    parsed = json_mapping(canonical({"value": value}).decode("utf-8"))["value"]
    if not isinstance(parsed, dict):
        raise JournalCodecError("approval execution payload is not an object")
    return parsed


def json_mapping(line: str) -> dict[str, JSONValue]:
    try:
        value = _load_json(line)
    except json.JSONDecodeError as exc:
        raise JournalCodecError("approval execution journal is malformed") from exc
    if not isinstance(value, dict):
        raise JournalCodecError("approval execution journal event is not an object")
    return _json_object(value)


def _json_object(value: dict[str, JSONValue]) -> dict[str, JSONValue]:
    return {key: _json_value(item) for key, item in value.items()}


def _json_value(value: JSONValue) -> JSONValue:
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return _json_object(value)
    return value
