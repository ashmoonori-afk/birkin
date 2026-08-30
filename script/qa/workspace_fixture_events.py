"""Canonical P1-6 event payloads for workspace QA fixtures."""

from __future__ import annotations

from birkin.office.job_types import OfficeJobState
from birkin.office.progress import office_progress_payload
from birkin.workspace.hub import EventSink


def emit_office_progress(emit: EventSink) -> None:
    """Emit every user-visible Office phase from the production mapper."""
    for state in (
        OfficeJobState.input_captured,
        OfficeJobState.operations_proposed,
        OfficeJobState.approved,
        OfficeJobState.validated,
        OfficeJobState.exported,
    ):
        progress = office_progress_payload("qa-progress", state)
        if progress is None:
            raise AssertionError(
                f"fixture Office state has no progress payload: {state}"
            )
        _ = emit("progress.updated", progress)


def emit_computer_update(emit: EventSink) -> None:
    """Emit the canonical successful computer-use fixture event."""
    _ = emit(
        "computer.updated",
        {
            "summary": "computer.action.completed · confirmed",
            "status": "confirmed",
            "ui_state": "succeeded",
            "kind": "computer_use",
            "receipt_ref": "sha256:fixture-receipt",
            "computer_sequence": 1,
            "focus_preserved": True,
        },
    )


def emit_approval_request(emit: EventSink, approval_id: str) -> None:
    """Emit one deterministic approval request with an opaque identity."""
    _ = emit(
        "approval.requested",
        {
            "approval_id": approval_id,
            "summary": "Approve deterministic workspace action",
            "status": "pending",
            "requester": "fixture-agent",
            "target": "workspace continuation",
            "expected_impact": "Resume the paused local action.",
            "rejection_result": "Keep the action paused without changes.",
            "related_evidence": f"fixture://approval/{approval_id}",
            "risk": "low",
            "expires_at": "end of this local QA session",
        },
    )


def emit_question_bundle(emit: EventSink) -> None:
    """Emit one question with its evidence and checkpoint."""
    _ = emit(
        "question.requested",
        {
            "question_id": "qa-question",
            "summary": "Continue with the inspected evidence?",
            "ui_state": "action_needed",
        },
    )
    _ = emit(
        "evidence.added",
        {
            "evidence_id": "qa-evidence",
            "summary": "workspace-report.txt",
            "path": "fixture://evidence/workspace-report.txt",
        },
    )
    _ = emit(
        "checkpoint.created",
        {
            "checkpoint_id": "a1b2c3d4",
            "summary": "Before workspace inspection",
        },
    )
