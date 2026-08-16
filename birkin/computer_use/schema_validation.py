"""Small validator for the shipped closed Computer Use schema subset."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def request_matches_schema(
    request: Mapping[str, Any],
    schema: Mapping[str, Any],
) -> bool:
    branches = schema.get("oneOf")
    if not isinstance(branches, list):
        return False
    return sum(_matches(request, branch) for branch in branches) == 1


def _matches(value: object, schema: object) -> bool:
    if not isinstance(schema, Mapping):
        return True
    alternatives = schema.get("oneOf")
    if isinstance(alternatives, list):
        return sum(_matches(value, item) for item in alternatives) == 1
    if "const" in schema and value != schema["const"]:
        return False
    options = schema.get("enum")
    if isinstance(options, list) and value not in options:
        return False
    expected = schema.get("type")
    if expected is not None and not _type_matches(value, expected):
        return False
    if isinstance(value, str):
        minimum = schema.get("minLength")
        maximum = schema.get("maxLength")
        if isinstance(minimum, int) and len(value) < minimum:
            return False
        if isinstance(maximum, int) and len(value) > maximum:
            return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        exclusive = schema.get("exclusiveMinimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            return False
        if isinstance(exclusive, (int, float)) and value <= exclusive:
            return False
        if isinstance(maximum, (int, float)) and value > maximum:
            return False
    if isinstance(value, Mapping):
        required = schema.get("required", ())
        if isinstance(required, Sequence) and any(key not in value for key in required):
            return False
        properties = schema.get("properties")
        if isinstance(properties, Mapping):
            if schema.get("additionalProperties") is False and any(
                key not in properties for key in value
            ):
                return False
            for key, item in value.items():
                child = properties.get(key)
                if child is not None and not _matches(item, child):
                    return False
    if isinstance(value, list):
        if schema.get("uniqueItems") is True and len(
            {repr(item) for item in value}
        ) != len(value):
            return False
        item_schema = schema.get("items")
        if item_schema is not None and any(
            not _matches(item, item_schema) for item in value
        ):
            return False
    return True


def _type_matches(value: object, expected: object) -> bool:
    if isinstance(expected, list):
        return any(_type_matches(value, item) for item in expected)
    return {
        "array": lambda item: isinstance(item, list),
        "boolean": lambda item: isinstance(item, bool),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "null": lambda item: item is None,
        "number": lambda item: (
            isinstance(item, (int, float)) and not isinstance(item, bool)
        ),
        "object": lambda item: isinstance(item, Mapping),
        "string": lambda item: isinstance(item, str),
    }.get(str(expected), lambda _item: False)(value)
