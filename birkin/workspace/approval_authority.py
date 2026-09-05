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

    before = store.get_pending(aid)
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
    follow_up_approval_id = result.get("follow_up_approval_id")
    if isinstance(follow_up_approval_id, str):
        return {
            "outcome": "follow_up_required",
            "approval_id": aid,
            "follow_up_approval_id": follow_up_approval_id,
            "question": str(result.get("error") or ""),
        }
    current: dict[str, object] | None = store.get_pending(aid)
    was_already_resolved = before is not None and before.get("status") != "pending"
    lost_pending_race = result.get("error") == "not found or already resolved"
    rejected_after_race = decision == "reject" and "error" not in result
    if (
        current is not None
        and current.get("status") != "pending"
        and (was_already_resolved or lost_pending_race or rejected_after_race)
    ):
        return {"outcome": "answered_elsewhere", "approval_id": aid}
    return {
        "outcome": "rejected_by_authority",
        "approval_id": aid,
        "error": str(result.get("error") or "approval could not be resolved")[:300],
    }
