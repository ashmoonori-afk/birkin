"""Typed JSON parsing for shared web POST routes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol, TypeAlias

from typing_extensions import assert_never, override

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


class _JsonLoader(Protocol):
    def __call__(self, s: bytes) -> JSONValue: ...


_load_json: _JsonLoader = json.loads


@dataclass(frozen=True, slots=True)
class RequestPayloadError(ValueError):
    detail: str

    @override
    def __str__(self) -> str:
        return self.detail


def parse_object(body: bytes) -> dict[str, JSONValue]:
    """Parse one JSON request object into recursively typed values."""
    try:
        value = _load_json(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RequestPayloadError("bad json") from exc
    if not isinstance(value, dict):
        raise RequestPayloadError("expected JSON object")
    return _object(value)


def string_list(value: JSONValue | None) -> list[str] | None:
    if not isinstance(value, list):
        return None
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            return None
        result.append(item)
    return result


def _object(value: dict[str, JSONValue]) -> dict[str, JSONValue]:
    return {key: _value(item) for key, item in value.items()}


def _value(value: JSONValue) -> JSONValue:
    match value:
        case None | str() | bool() | int() | float():
            return value
        case list() as items:
            return [_value(item) for item in items]
        case dict() as mapping:
            return _object(mapping)
        case unreachable:
            assert_never(unreachable)
