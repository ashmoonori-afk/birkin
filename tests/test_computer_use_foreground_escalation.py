from __future__ import annotations

from pathlib import Path
from typing import Any

from birkin.computer_use.artifacts import ArtifactStore
from birkin.computer_use.service import ComputerUseService
from tests.computer_use_fakes import FakeBackend
from tests.test_computer_use_service import _capture


def _double_click(
    captured: dict[str, Any],
    *,
    delivery: str,
    idempotency_key: str,
    prior_receipt: str | None = None,
    approval_id: str | None = None,
) -> dict[str, Any]:
    element = captured["elements"][0]
    return {
        "version": 1,
        "action": "double_click",
        "session_id": captured["session_id"],
        "action_id": "action-double-click",
        "idempotency_key": idempotency_key,
        "target": {
            "app_ref": captured["app_ref"],
            "window_ref": captured["window_ref"],
            "snapshot_ref": captured["snapshot_ref"],
            "element_ref": element["element_ref"],
        },
        "delivery": delivery,
        "predicted_effect": {
            "property": "value",
            "operation": "equals",
            "value": "clicked",
        },
        "prior_background_receipt": prior_receipt,
        "approval_id": approval_id,
    }


def test_foreground_requires_background_evidence_and_exact_approval(
    tmp_path: Path,
) -> None:
    backend = FakeBackend()
    service = ComputerUseService(
        backend=backend,
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        session_id="session-a",
    )
    captured = _capture(service)

    background = service.execute(
        _double_click(
            captured,
            delivery="background",
            idempotency_key="attempt-background",
        )
    )
    unapproved = service.execute(
        _double_click(
            captured,
            delivery="foreground",
            idempotency_key="attempt-unapproved",
            prior_receipt=background["receipt_ref"],
        )
    )
    request = _double_click(
        captured,
        delivery="foreground",
        idempotency_key="attempt-approved",
        prior_receipt=background["receipt_ref"],
    )
    approval_id = service.approvals.propose(
        intent_digest=service.intent_digest(request),
        prior_receipt=background["receipt_ref"],
    )
    service.approvals.approve(approval_id, actor="user")
    request["approval_id"] = approval_id
    approved = service.execute(request)

    assert background["refusal_code"] == "background_delivery_unsupported"
    assert background["mutation_dispatched"] is False
    assert unapproved["refusal_code"] == "foreground_approval_required"
    assert approved["ok"] is True
    assert approved["delivery"] == "foreground"
    assert backend.foreground_count == 1


def test_foreground_approval_is_one_shot_and_digest_bound(
    tmp_path: Path,
) -> None:
    backend = FakeBackend()
    service = ComputerUseService(
        backend=backend,
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        session_id="session-a",
    )
    captured = _capture(service)
    background = service.execute(
        _double_click(
            captured,
            delivery="background",
            idempotency_key="attempt-background",
        )
    )
    request = _double_click(
        captured,
        delivery="foreground",
        idempotency_key="attempt-approved",
        prior_receipt=background["receipt_ref"],
    )
    approval_id = service.approvals.propose(
        intent_digest=service.intent_digest(request),
        prior_receipt=background["receipt_ref"],
    )
    service.approvals.approve(approval_id, actor="user")
    request["approval_id"] = approval_id

    first = service.execute(request)
    consumed = service.approvals.consume(
        approval_id,
        intent_digest=service.intent_digest(request),
        prior_receipt=background["receipt_ref"],
    )
    replay = dict(request, idempotency_key="attempt-replay")
    second = service.execute(replay)

    assert first["ok"] is True
    assert consumed == "foreground_approval_expired"
    assert second["ok"] is False
    assert second["refusal_code"] == "stale_ref"
    assert backend.foreground_count == 1
