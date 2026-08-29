"""Workspace command authority for canonical approval decisions."""

from __future__ import annotations

from collections.abc import Callable

from birkin import approvals, store

RuntimeEventSink = Callable[[str, dict[str, object]], None]


def decide(
    aid: str,
    *,
    decision: str,
    reason: str = "",
    on_event: RuntimeEventSink | None = None,
) -> dict[str, object]:
    """Resolve once and normalize a multi-surface losing answer."""

    if decision == "approve":
        result: dict[str, object] = approvals.approve(
            aid,
            approved_by="human:workspace",
            approved_via="workspace:control",
            on_event=on_event,
        )
        decided_status = "approved"
    elif decision == "reject":
        result = approvals.reject(
            aid,
            reason=reason,
            rejected_by="human:workspace",
            rejected_via="workspace:control",
        )
        decided_status = "rejected"
    else:
        raise ValueError("decision must be approve or reject")
    if result.get("ok"):
        response: dict[str, object] = {
            "outcome": decided_status,
            "approval_id": aid,
        }
        if "result" in result:
            response["receipt"] = str(result["result"])
        return response
    current: dict[str, object] | None = store.get_pending(aid)
    if current is not None and current.get("status") != "pending":
        return {"outcome": "answered_elsewhere", "approval_id": aid}
    return {
        "outcome": "rejected_by_authority",
        "approval_id": aid,
        "error": str(result.get("error") or "approval could not be resolved")[:300],
    }
