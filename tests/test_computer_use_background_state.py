from __future__ import annotations

from pathlib import Path

from birkin.computer_use.artifacts import ArtifactStore
from birkin.computer_use.service import ComputerUseService
from tests.computer_use_fakes import FakeBackend, fake_session_capability
from tests.test_computer_use_service import _capture, _mutation


def test_background_focus_change_fails_verification(tmp_path: Path) -> None:
    backend = FakeBackend()
    backend.change_focus_on_mutation = True
    service = ComputerUseService(
        backend=backend,
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        session_id="session-a",
        session_capability=fake_session_capability(),
    )
    captured = _capture(service)

    result = service.execute(_mutation(captured))

    assert result["ok"] is False
    assert result["effect"] == "unverifiable"
    assert result["refusal_code"] == "background_state_changed"
    assert result["focus"]["preserved"] is False


def test_pointer_motion_does_not_impersonate_focus_change(tmp_path: Path) -> None:
    backend = FakeBackend()
    backend.move_pointer_on_mutation = True
    service = ComputerUseService(
        backend=backend,
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        session_id="session-a",
        session_capability=fake_session_capability(),
    )
    captured = _capture(service)

    result = service.execute(_mutation(captured))

    assert result["ok"] is True
    assert result["focus"]["preserved"] is True


def test_foreground_receipt_proves_release_and_focus_restore(
    tmp_path: Path,
) -> None:
    backend = FakeBackend()
    service = ComputerUseService(
        backend=backend,
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        session_id="session-a",
        session_capability=fake_session_capability(),
    )
    captured = _capture(service)
    from tests.test_computer_use_foreground_escalation import _double_click

    background = service.execute(
        _double_click(
            captured,
            delivery="background",
            idempotency_key="background",
        )
    )
    request = _double_click(
        captured,
        delivery="foreground",
        idempotency_key="foreground",
        prior_receipt=background["receipt_ref"],
    )
    approval_id = service.approvals.propose(
        intent_digest=service.intent_digest(request),
        prior_receipt=background["receipt_ref"],
    )
    service.approvals.approve(approval_id, actor="user")
    request["approval_id"] = approval_id

    result = service.execute(request)

    assert result["ok"] is True
    assert result["restoration"] == {
        "focus_restored": True,
        "released_inputs": ["shift", "mouse_left"],
    }
    assert backend.restore_count == 1
    assert backend.release_count == 1
