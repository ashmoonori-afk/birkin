from __future__ import annotations

from typing import Any

from birkin.computer_use.schema import ACTIONS, computer_use_schema
from birkin.computer_use.schema_validation import request_matches_schema

EXPECTED_ACTIONS = {
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
}


def _branch(schema: dict[str, Any], action: str) -> dict[str, Any]:
    return next(
        branch
        for branch in schema["oneOf"]
        if branch["properties"]["action"].get("const") == action
    )


def test_schema_exposes_one_closed_branch_per_action() -> None:
    schema = computer_use_schema()

    assert set(ACTIONS) == EXPECTED_ACTIONS
    assert {
        branch["properties"]["action"]["const"] for branch in schema["oneOf"]
    } == EXPECTED_ACTIONS
    assert all(branch["additionalProperties"] is False for branch in schema["oneOf"])


def test_capture_modes_and_target_shapes_are_typed() -> None:
    capture = _branch(computer_use_schema(), "capture")

    assert capture["properties"]["mode"]["enum"] == ["som", "vision", "ax"]
    target = capture["properties"]["target"]
    assert target["oneOf"] == [
        {
            "type": "object",
            "required": ["app_ref"],
            "properties": {"app_ref": {"type": "string", "minLength": 1}},
            "additionalProperties": False,
        },
        {
            "type": "object",
            "required": ["window_ref"],
            "properties": {"window_ref": {"type": "string", "minLength": 1}},
            "additionalProperties": False,
        },
    ]


def test_element_mutations_require_current_opaque_refs() -> None:
    schema = computer_use_schema()
    for action in (
        "click",
        "double_click",
        "right_click",
        "middle_click",
        "scroll",
        "type",
    ):
        branch = _branch(schema, action)
        assert "target" in branch["required"]
        target = branch["properties"]["target"]
        assert target["required"] == [
            "app_ref",
            "window_ref",
            "snapshot_ref",
            "element_ref",
        ]
        assert "x" not in target["properties"]
        assert "y" not in target["properties"]


def test_runtime_validator_rejects_oversized_text_and_extra_fields() -> None:
    schema = computer_use_schema()
    oversized = {
        "version": 1,
        "action": "type",
        "session_id": "session",
        "action_id": "action",
        "idempotency_key": "idempotency",
        "target": {
            "app_ref": "app",
            "window_ref": "window",
            "snapshot_ref": "snapshot",
            "element_ref": "element",
        },
        "text": "x" * 32769,
        "predicted_effect": {
            "property": "value",
            "operation": "equals",
            "value": "value",
        },
    }

    assert request_matches_schema(oversized, schema) is False
    assert (
        request_matches_schema(
            {"version": 1, "action": "doctor", "unexpected": True},
            schema,
        )
        is False
    )
