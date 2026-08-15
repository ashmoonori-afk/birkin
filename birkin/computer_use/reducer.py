"""Canonical pure reducer for Computer Use UI and replay state."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .events import ComputerEvent


@dataclass(frozen=True, slots=True)
class ComputerState:
    sequence: int = 0
    session_id: str | None = None
    snapshot_ref: str | None = None
    artifact_refs: tuple[str, ...] = ()
    receipt_refs: tuple[str, ...] = ()
    last_effect: str | None = None
    permission_code: str | None = None
    focus_preserved: bool | None = None
    approval_id: str | None = None
    approval_status: str | None = None


def reduce_event(
    state: ComputerState,
    event: ComputerEvent,
) -> ComputerState:
    if event.version != 1:
        raise ValueError("unsupported Computer Use event version")
    if event.sequence != state.sequence + 1:
        raise ValueError("non-contiguous Computer Use event sequence")
    if state.session_id is not None and event.session_id != state.session_id:
        raise ValueError("cross-session Computer Use event")
    next_state = replace(
        state,
        sequence=event.sequence,
        session_id=event.session_id,
    )
    snapshot = event.payload.get("snapshot_ref")
    if isinstance(snapshot, str):
        next_state = replace(next_state, snapshot_ref=snapshot)
    artifact = event.payload.get("artifact")
    if isinstance(artifact, dict):
        artifact_ref = artifact.get("ref")
        if isinstance(artifact_ref, str):
            next_state = replace(
                next_state,
                artifact_refs=(*next_state.artifact_refs, artifact_ref),
            )
    receipt = event.payload.get("receipt_ref")
    if isinstance(receipt, str):
        next_state = replace(
            next_state,
            receipt_refs=(*next_state.receipt_refs, receipt),
        )
    effect = event.payload.get("effect")
    if isinstance(effect, str):
        next_state = replace(next_state, last_effect=effect)
    refusal = event.payload.get("refusal_code")
    if event.kind == "computer.permission.required" and isinstance(refusal, str):
        next_state = replace(next_state, permission_code=refusal)
    focus = event.payload.get("focus")
    if isinstance(focus, dict) and isinstance(focus.get("preserved"), bool):
        next_state = replace(next_state, focus_preserved=focus["preserved"])
    approval_id = event.payload.get("approval_id")
    if isinstance(approval_id, str):
        next_state = replace(
            next_state,
            approval_id=approval_id,
            approval_status=(
                "action_needed"
                if refusal == "background_delivery_unsupported"
                else "consuming"
            ),
        )
    if effect == "confirmed" and next_state.approval_id is not None:
        next_state = replace(next_state, approval_status="consumed")
    if refusal == "foreground_approval_expired":
        next_state = replace(next_state, approval_status="expired")
    return next_state
