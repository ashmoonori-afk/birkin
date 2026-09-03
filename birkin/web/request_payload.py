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

# json.loads happily accepts nesting far deeper than the typed re-walk below can
# recurse through, and the resulting RecursionError is not a RequestPayloadError,
# so the route handler would answer nothing at all. Bound the walk instead: no
# request this API serves nests anywhere near this deep.
MAX_NESTING_DEPTH = 32
_TOO_DEEP = "JSON nesting too deep"


@dataclass(frozen=True, slots=True)
class RequestPayloadError(ValueError):
    detail: str

    @override
    def __str__(self) -> str:
        return self.detail


def parse_value(body: bytes) -> JSONValue:
    """Parse one JSON request body, bounding its nesting on every platform.

    Whether json.loads even reaches the end of an over-nested body depends on
    the interpreter's C recursion limit, which is per-platform: 5000 nested
    arrays parse fine on Linux and macOS and raise RecursionError on Windows.
    So the depth bound is applied to the parsed value too, before the caller
    ever sees it -- both paths answer with the same _TOO_DEEP detail.
    """
    try:
        value = _load_json(body)
    except ValueError as exc:
        # Invalid syntax, undecodable bytes and interpreter integer limits are all
        # bounded refusals; only JSONDecodeError of these is a decode error.
        raise RequestPayloadError("bad json") from exc
    except RecursionError as exc:
        raise RequestPayloadError(_TOO_DEEP) from exc
    try:
        return _value(value, 0)
    except RecursionError as exc:
        raise RequestPayloadError(_TOO_DEEP) from exc


def parse_object(body: bytes) -> dict[str, JSONValue]:
    """Parse one JSON request object into recursively typed values."""
    value = parse_value(body)
    if not isinstance(value, dict):
        raise RequestPayloadError("expected JSON object")
    return value


def string_list(value: JSONValue | None) -> list[str] | None:
    if not isinstance(value, list):
        return None
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            return None
        result.append(item)
    return result


def _object(value: dict[str, JSONValue], depth: int) -> dict[str, JSONValue]:
    if depth > MAX_NESTING_DEPTH:
        raise RequestPayloadError(_TOO_DEEP)
    return {key: _value(item, depth) for key, item in value.items()}


def _value(value: JSONValue, depth: int) -> JSONValue:
    match value:
        case None | str() | bool() | int() | float():
            return value
        case list() as items:
            if depth > MAX_NESTING_DEPTH:
                raise RequestPayloadError(_TOO_DEEP)
            return [_value(item, depth + 1) for item in items]
        case dict() as mapping:
            return _object(mapping, depth + 1)
        case unreachable:
            assert_never(unreachable)
