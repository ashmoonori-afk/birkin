"""Approvals router — review and decide on pending agent actions."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from birkin.core.approval.gate import ApprovalGate

router = APIRouter(prefix="/api/approvals", tags=["approvals"])

_gate: ApprovalGate | None = None


def _get_gate() -> ApprovalGate:
    global _gate
    if _gate is None:
        _gate = ApprovalGate()
    return _gate


class ApproveRequest(BaseModel):
    modified_payload: Optional[dict[str, Any]] = None
    note: Optional[str] = None


class RejectRequest(BaseModel):
    note: Optional[str] = None


@router.get("/pending")
async def list_pending() -> list[dict[str, Any]]:
    """List all actions awaiting approval."""
    gate = _get_gate()
    return [a.model_dump() for a in gate.list_pending()]


@router.post("/{action_id}/approve")
async def approve_action(action_id: str, body: ApproveRequest) -> dict[str, Any]:
    """Approve a pending action."""
    gate = _get_gate()
    ok = gate.approve(action_id, modified_payload=body.modified_payload, note=body.note)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Action not found or already decided: {action_id}")
    return {"id": action_id, "status": "approved"}


@router.post("/{action_id}/reject")
async def reject_action(action_id: str, body: RejectRequest) -> dict[str, Any]:
    """Reject a pending action."""
    gate = _get_gate()
    ok = gate.reject(action_id, note=body.note)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Action not found or already decided: {action_id}")
    return {"id": action_id, "status": "rejected"}
