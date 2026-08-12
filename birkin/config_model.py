"""Versioned schema and boundary normalization for ``config.json``."""

from __future__ import annotations

import copy
import json
import warnings
from collections.abc import Mapping
from importlib import resources
from typing import Any, TypeAlias, cast

CONFIG_SCHEMA_VERSION = 1


Config: TypeAlias = dict[str, Any]


def _json_type(value: object) -> str | list[str]:
    if value is None:
        return ["string", "null"]
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise TypeError(f"unsupported config default: {type(value).__name__}")


def _inferred_schema(value: object, path: str) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": _json_type(value),
        "default": copy.deepcopy(value),
        "description": f"Birkin setting `{path}`.",
        "x-description-ko": f"Birkin 설정 `{path}`.",
    }
    if isinstance(value, dict):
        schema["additionalProperties"] = True
        schema["properties"] = {
            str(key): _inferred_schema(child, f"{path}.{key}".strip("."))
            for key, child in value.items()
        }
    elif isinstance(value, list) and value:
        schema["items"] = {"type": _json_type(value[0])}
    return schema


def _merge_schema(base: dict[str, Any], overlay: Mapping[str, Any]) -> None:
    for key, value in overlay.items():
        if key == "properties" and isinstance(value, Mapping):
            props = base.setdefault("properties", {})
            for name, child in value.items():
                target = props.setdefault(name, {})
                if isinstance(target, dict) and isinstance(child, Mapping):
                    _merge_schema(target, child)
            continue
        base[key] = copy.deepcopy(value)


def load_config_schema(
    defaults: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the v1 schema, completed from the runtime default tree."""
    path = resources.files("birkin").joinpath("schemas/config-v1.schema.json")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise TypeError("config schema must be an object")
    schema = cast(dict[str, Any], loaded)
    if defaults is None:
        return schema
    inferred = _inferred_schema(dict(defaults), "")
    inferred.update({
        key: copy.deepcopy(value)
        for key, value in schema.items()
        if key != "properties"
    })
    _merge_schema(inferred, {"properties": schema.get("properties", {})})
    return inferred


def defaults_from_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Rebuild the complete default tree from property defaults."""
    props = schema.get("properties")
    if not isinstance(props, Mapping):
        return {}
    out: dict[str, Any] = {}
    for key, raw in props.items():
        if not isinstance(raw, Mapping) or "default" not in raw:
            continue
        out[str(key)] = copy.deepcopy(raw["default"])
    return out


def _type_ok(value: object, expected: object) -> bool:
    if isinstance(expected, list):
        return any(_type_ok(value, item) for item in expected)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "null":
        return value is None
    return True


def _valid(value: object, schema: Mapping[str, Any]) -> bool:
    if not _type_ok(value, schema.get("type")):
        return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            return False
        if "maximum" in schema and value > schema["maximum"]:
            return False
    if isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            return all(_valid(item, item_schema) for item in value)
    return True


def normalize_overrides(
    raw: Mapping[str, Any],
    defaults: Mapping[str, Any],
) -> dict[str, Any]:
    """Drop invalid known leaves while preserving extensions and siblings."""
    schema = load_config_schema(defaults)

    def walk(
        value: Mapping[str, Any],
        node: Mapping[str, Any],
        path: str,
    ) -> dict[str, Any]:
        props = node.get("properties")
        known = props if isinstance(props, Mapping) else {}
        out: dict[str, Any] = {}
        for key, child in value.items():
            child_schema = known.get(key)
            child_path = f"{path}.{key}"
            if not isinstance(child_schema, Mapping):
                out[key] = copy.deepcopy(child)
                continue
            if not _valid(child, child_schema):
                warnings.warn(
                    f"invalid config at {child_path}; using default",
                    RuntimeWarning,
                    stacklevel=3,
                )
                continue
            if isinstance(child, Mapping):
                out[key] = walk(child, child_schema, child_path)
            else:
                out[key] = copy.deepcopy(child)
        return out

    return walk(raw, schema, "$")


def merge_config(
    defaults: Mapping[str, Any],
    overrides: Mapping[str, Any],
) -> Config:
    """Recursively merge sparse overrides into independent default copies."""
    out: dict[str, Any] = copy.deepcopy(dict(defaults))
    for key, value in overrides.items():
        current = out.get(key)
        if isinstance(current, dict) and isinstance(value, Mapping):
            out[key] = merge_config(current, value)
        else:
            out[key] = copy.deepcopy(value)
    return out
