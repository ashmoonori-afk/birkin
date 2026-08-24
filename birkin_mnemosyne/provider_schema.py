"""Machine schema requested from the Codex curation provider."""

from __future__ import annotations

from .json_types import JsonObject


def curation_plan_schema() -> JsonObject:
    """Return the strict CurationPlan/1 schema accepted by the executor."""
    nullable_string: JsonObject = {"type": ["string", "null"]}
    operation_properties: JsonObject = {
        "op": {"type": "string"},
        "slug": dict(nullable_string),
        "zone": dict(nullable_string),
        "a": dict(nullable_string),
        "b": dict(nullable_string),
        "stale": dict(nullable_string),
        "by": dict(nullable_string),
        "reason": dict(nullable_string),
    }
    operation: JsonObject = {
        "type": "object",
        "required": [
            "op",
            "slug",
            "zone",
            "a",
            "b",
            "stale",
            "by",
            "reason",
        ],
        "properties": operation_properties,
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "required": ["plan_version", "ops", "summary"],
        "properties": {
            "plan_version": {"type": "integer", "const": 1},
            "summary": {"type": "string"},
            "ops": {"type": "array", "items": operation},
        },
        "additionalProperties": False,
    }
