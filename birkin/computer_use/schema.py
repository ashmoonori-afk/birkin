"""Public JSON schema for the single ``computer_use`` tool."""

from __future__ import annotations

from typing import Any, Final

from .schema_common import (
    STRING_REF,
    branch,
    element_target_schema,
    mutation_properties,
    mutation_required,
    target_schema,
)

ACTIONS: Final[tuple[str, ...]] = (
    "capture",
    "list_apps",
    "list_windows",
    "click",
    "double_click",
    "right_click",
    "middle_click",
    "drag",
    "scroll",
    "type",
    "doctor",
)


def _click_branches() -> list[dict[str, Any]]:
    return [
        branch(
            action,
            properties=mutation_properties(),
            required=mutation_required(),
        )
        for action in (
            "click",
            "double_click",
            "right_click",
            "middle_click",
        )
    ]


def _branches() -> list[dict[str, Any]]:
    capture = branch(
        "capture",
        properties={
            "session_id": dict(STRING_REF),
            "mode": {"type": "string", "enum": ["som", "vision", "ax"]},
            "target": target_schema(),
        },
        required=("session_id", "mode", "target"),
    )
    list_apps = branch("list_apps", properties={"session_id": dict(STRING_REF)})
    list_windows = branch(
        "list_windows",
        properties={
            "session_id": dict(STRING_REF),
            "app_ref": dict(STRING_REF),
        },
    )
    drag_properties = mutation_properties()
    drag_properties["start"] = drag_properties.pop("target")
    drag_properties["end"] = element_target_schema()
    drag = branch(
        "drag",
        properties=drag_properties,
        required=(
            "session_id",
            "action_id",
            "idempotency_key",
            "start",
            "end",
            "predicted_effect",
        ),
    )
    scroll_properties = mutation_properties() | {
        "axis": {"type": "string", "enum": ["horizontal", "vertical"]},
        "direction": {"type": "string", "enum": ["negative", "positive"]},
        "amount": {"type": "number", "exclusiveMinimum": 0},
    }
    scroll = branch(
        "scroll",
        properties=scroll_properties,
        required=(*mutation_required(), "axis", "direction", "amount"),
    )
    type_properties = mutation_properties() | {
        "text": {"type": "string", "maxLength": 32768},
        "mode": {
            "type": "string",
            "enum": ["replace", "insert", "append"],
            "default": "replace",
        },
    }
    type_text = branch(
        "type",
        properties=type_properties,
        required=(*mutation_required(), "text"),
    )
    doctor = branch("doctor")
    return [
        capture,
        list_apps,
        list_windows,
        *_click_branches(),
        drag,
        scroll,
        type_text,
        doctor,
    ]


def computer_use_schema() -> dict[str, Any]:
    """Return the closed discriminated union accepted by ``computer_use``."""
    return {"oneOf": _branches()}
