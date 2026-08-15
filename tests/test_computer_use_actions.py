from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from birkin.computer_use.artifacts import ArtifactStore
from birkin.computer_use.service import ComputerUseService
from tests.computer_use_fakes import FakeBackend
from tests.test_computer_use_service import _capture


def _service(
    tmp_path: Path,
    backend: FakeBackend,
) -> ComputerUseService:
    return ComputerUseService(
        backend=backend,
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        session_id="session-a",
    )


def _target(captured: dict[str, Any]) -> dict[str, str]:
    return {
        "app_ref": captured["app_ref"],
        "window_ref": captured["window_ref"],
        "snapshot_ref": captured["snapshot_ref"],
        "element_ref": captured["elements"][0]["element_ref"],
    }


def _base(
    captured: dict[str, Any],
    action: str,
) -> dict[str, Any]:
    return {
        "version": 1,
        "action": action,
        "session_id": captured["session_id"],
        "action_id": f"action-{action}",
        "idempotency_key": f"idempotency-{action}",
        "target": _target(captured),
        "delivery": "background",
    }


@pytest.mark.parametrize(
    ("action", "semantic"),
    [
        ("click", "press"),
        ("double_click", "double_click"),
        ("right_click", "show_menu"),
        ("middle_click", "middle_click"),
    ],
)
def test_click_family_uses_explicit_semantic_actions(
    tmp_path: Path,
    action: str,
    semantic: str,
) -> None:
    backend = FakeBackend()
    backend.element = replace(
        backend.element,
        supported_actions=frozenset({semantic}),
    )
    service = _service(tmp_path, backend)
    captured = _capture(service)
    request = _base(captured, action)
    request["predicted_effect"] = {
        "property": "value",
        "operation": "equals",
        "value": "clicked",
    }

    result = service.execute(request)

    assert result["ok"] is True
    assert result["effect"] == "confirmed"


def test_drag_scroll_type_and_key_are_typed_and_verified(
    tmp_path: Path,
) -> None:
    cases = [
        ("drag", "drag", "dragged"),
        ("scroll", "scroll", "scrolled"),
        ("type", "set_value", "typed"),
        ("key", "key", "key:Return"),
    ]
    for action, semantic, expected in cases:
        backend = FakeBackend()
        backend.element = replace(
            backend.element,
            supported_actions=frozenset({semantic}),
        )
        service = _service(tmp_path, backend)
        captured = _capture(service)
        request = _base(captured, action)
        request["predicted_effect"] = {
            "property": "value",
            "operation": "equals",
            "value": expected,
        }
        if action == "drag":
            request["start"] = request.pop("target")
            request["end"] = dict(request["start"])
        elif action == "scroll":
            request.update(
                axis="vertical",
                direction="positive",
                amount=1,
            )
        elif action == "type":
            request.update(text="typed", mode="replace")
        elif action == "key":
            request["chord"] = {"key": "Return", "modifiers": []}

        result = service.execute(request)

        assert result["ok"] is True, (action, result)
        assert result["effect"] == "confirmed"
        assert backend.last_command is not None
        if action == "drag":
            assert (
                backend.last_command.secondary_accessibility_identity
                == backend.element.accessibility_identity
            )
        elif action == "scroll":
            assert backend.last_command.axis == "vertical"
            assert backend.last_command.amount == 1
        elif action == "key":
            assert backend.last_command.modifiers == ()
