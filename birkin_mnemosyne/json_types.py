"""Recursive JSON value types used at serialized-data boundaries."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TypeAlias

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

_LOADS: Callable[[str], JsonValue] = json.loads


def load_json(text: str) -> JsonValue:
    """Decode JSON into its recursive runtime value union."""
    return _LOADS(text)
