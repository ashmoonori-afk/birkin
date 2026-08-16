"""Typed projections and commands for the authenticated approval console."""

from __future__ import annotations

from typing import Any

from .. import agentruns, approvals, store, uistate


_TERMINAL = {"done", "error", "stale"}


def _flatten(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flat: list[dict[str, Any]] = []
    for run in runs:
        item = dict(run)
        children = item.pop("children", [])
        flat.append(item)
        if isinstance(children, list):
            flat.extend(_flatten(children))
    return flat


def _approval_run_id(record: dict[str, Any]) -> str:
    payload = record.get("payload")
    candidate = payload.get("run_id") if isinstance(payload, dict) else None
    if isinstance(candidate, str):
        return candidate
    origin = str(record.get("origin") or "")
    return origin.removeprefix("agent:") if origin.startswith("agent:") else ""


def _pending_by_run() -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for approval in approvals.reviewable_pending():
        run_id = _approval_run_id(approval)
        if run_id:
            grouped.setdefault(run_id, []).append(approval)
    return grouped


def _status(run: dict[str, Any], pending: int) -> str:
    if run.get("status") in _TERMINAL:
        return "done"
    if pending:
        return "waiting-approval"
    if run.get("control_state") == "blocked" or run.get("stalled"):
        return "blocked"
    return "running"


def _ui_state(run: dict[str, Any], pending: int) -> str:
    if run.get("status") in _TERMINAL:
        return uistate.from_agent_run(str(run.get("status"))).state
    if pending:
        return uistate.from_approval({"status": "pending"}).state
    if run.get("control_state") == "blocked" or run.get("stalled"):
        return uistate.from_goal("paused").state
    return uistate.from_agent_run(str(run.get("status"))).state


def _summary(run: dict[str, Any], pending: int) -> dict[str, Any]:
    status = _status(run, pending)
    return {
        "id": run["id"],
        "parent_id": run.get("parent_id"),
        "task": run.get("task", ""),
        "status": status,
        "ui_state": _ui_state(run, pending),
        "terminal": status == "done",
        "runtime_status": run.get("status"),
        "started_at": run.get("started_at", ""),
        "last_heartbeat": run.get("last_heartbeat", ""),
        "heartbeat_age": run.get("heartbeat_age", 0),
        "pending_approvals": pending,
        "result": run.get("result", ""),
    }


def list_runs() -> dict[str, list[dict[str, Any]]]:
    """Return newest-first flat run summaries for a compact remote console."""
    pending = _pending_by_run()
    rows = [
        _summary(run, len(pending.get(run["id"], [])))
        for run in _flatten(agentruns.list_runs())
    ]
    rows.sort(key=lambda row: (row["started_at"], row["id"]), reverse=True)
    return {"runs": rows}


def run_detail(run_id: str) -> tuple[int, dict[str, Any]]:
    run = agentruns.get_run(run_id)
    if run is None:
        return 404, {"error": "run not found"}
    pending = _pending_by_run().get(run_id, [])
    age = agentruns._age_seconds(run.get("last_heartbeat"))
    run["heartbeat_age"] = age
    run["stalled"] = run.get("status") == "running" and age > agentruns.STALE_AFTER_SECONDS
    detail = _summary(run, len(pending))
    detail["events"] = run.get("events", [])
    detail["approvals"] = pending
    return 200, detail


def control_run(run_id: str, action: Any, text: Any = "") -> tuple[int, dict[str, Any]]:
    """Apply one legal durable control transition through the run authority."""
    if not isinstance(action, str) or action not in {"steer", "abort", "resume"}:
        return 400, {"error": "action must be steer, abort, or resume"}
    message = str(text or "").strip()
    result = agentruns.control(run_id, action, message)
    if result is None:
        return 404, {"error": "run not found"}
    if not result.get("ok"):
        return 409, {"error": result.get("error", "invalid run transition")}
    code, detail = run_detail(run_id)
    return code, detail


def action_receipt(action_id: str) -> tuple[int, dict[str, Any]]:
    record = store.get_pending(action_id)
    if record is None:
        return 404, {"error": "action not found"}
    if record.get("status") != "approved" or "action_receipt" not in record:
        return 409, {"error": "action has no execution receipt"}
    return 200, {
        "id": record["id"],
        "category": record.get("category", ""),
        "status": record["status"],
        "executed_at": record.get("resolved_at", ""),
        "receipt": record["action_receipt"],
    }
