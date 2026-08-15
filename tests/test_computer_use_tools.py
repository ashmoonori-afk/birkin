from __future__ import annotations

import json
from pathlib import Path

from birkin.computer_use.artifacts import ArtifactStore
from birkin.computer_use.service import ComputerUseService
from birkin.tools import ToolContext, build_registry
from tests.computer_use_fakes import FakeBackend


def _context(
    tmp_path: Path,
    *,
    enabled: bool,
) -> ToolContext:
    context = ToolContext(
        cfg={
            "desktop_tools": enabled,
            "spill_threshold": 0,
            "computer_use": {
                "enabled": enabled,
                "allowed_apps": ["org.birkin.QAFixture"],
            },
        },
        client=None,
        cwd=tmp_path,
    )
    context.computer_use_service = ComputerUseService(
        backend=FakeBackend(),
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        session_id="session-a",
    )
    return context


def test_computer_use_is_opt_in_with_existing_desktop_group(
    tmp_path: Path,
) -> None:
    disabled = build_registry(_context(tmp_path, enabled=False))
    enabled = build_registry(_context(tmp_path, enabled=True))

    assert "computer_use" not in disabled.names()
    assert {"computer_use", "desktop_windows", "window_screenshot"} <= set(
        enabled.names()
    )


def test_desktop_screenshots_do_not_enable_computer_use(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, enabled=True)
    context.cfg["computer_use"] = {"enabled": False}

    registry = build_registry(context)

    assert "desktop_windows" in registry.names()
    assert "computer_use" not in registry.names()


def test_computer_use_exposes_one_closed_typed_tool(tmp_path: Path) -> None:
    registry = build_registry(_context(tmp_path, enabled=True))

    spec = next(item for item in registry.specs() if item["name"] == "computer_use")

    assert spec["input_schema"]["oneOf"]
    assert all(
        branch["additionalProperties"] is False
        for branch in spec["input_schema"]["oneOf"]
    )


def test_tool_returns_structured_doctor_and_invalid_input(
    tmp_path: Path,
) -> None:
    registry = build_registry(_context(tmp_path, enabled=True))

    doctor = registry.execute(
        "computer_use",
        {"version": 1, "action": "doctor"},
    )
    invalid = registry.execute(
        "computer_use",
        {"version": 1, "action": "not_an_action"},
    )

    assert doctor.is_error is False
    assert isinstance(doctor.content, str)
    assert json.loads(doctor.content)["session_id"] == "session-a"
    assert invalid.is_error is True
    assert isinstance(invalid.content, str)
    assert json.loads(invalid.content)["refusal_code"] == "invalid_request"
