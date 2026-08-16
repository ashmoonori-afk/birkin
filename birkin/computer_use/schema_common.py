"""Reusable closed JSON-schema fragments for Computer Use."""

from __future__ import annotations

from typing import Any

STRING_REF = {"type": "string", "minLength": 1}


def target_schema() -> dict[str, Any]:
    return {
        "oneOf": [
            {
                "type": "object",
                "required": ["app_ref"],
                "properties": {"app_ref": dict(STRING_REF)},
                "additionalProperties": False,
            },
            {
                "type": "object",
                "required": ["window_ref"],
                "properties": {"window_ref": dict(STRING_REF)},
                "additionalProperties": False,
            },
        ]
    }


def element_target_schema() -> dict[str, Any]:
    required = [
        "app_ref",
        "window_ref",
        "snapshot_ref",
        "element_ref",
    ]
    return {
        "type": "object",
        "required": required,
        "properties": {name: dict(STRING_REF) for name in required},
        "additionalProperties": False,
    }


def branch(
    action: str,
    *,
    properties: dict[str, Any] | None = None,
    required: tuple[str, ...] = (),
) -> dict[str, Any]:
    action_properties: dict[str, Any] = {
        "version": {"type": "integer", "const": 1, "default": 1},
        "action": {"type": "string", "const": action},
    }
    action_properties.update(properties or {})
    return {
        "type": "object",
        "required": ["action", *required],
        "properties": action_properties,
        "additionalProperties": False,
    }


def mutation_properties() -> dict[str, Any]:
    return {
        "session_id": dict(STRING_REF),
        "action_id": dict(STRING_REF),
        "idempotency_key": dict(STRING_REF),
        "target": element_target_schema(),
        "delivery": {
            "type": "string",
            "enum": ["background", "foreground"],
            "default": "background",
        },
        "predicted_effect": {
            "type": "object",
            "required": ["property", "operation"],
            "properties": {
                "property": dict(STRING_REF),
                "operation": {
                    "type": "string",
                    "enum": ["equals", "changes", "appears", "disappears"],
                },
                "value": {},
            },
            "additionalProperties": False,
        },
        "prior_background_receipt": {
            "type": ["string", "null"],
            "minLength": 1,
        },
        "approval_id": {"type": ["string", "null"], "minLength": 1},
    }


def mutation_required() -> tuple[str, ...]:
    return (
        "session_id",
        "action_id",
        "idempotency_key",
        "target",
        "predicted_effect",
    )
