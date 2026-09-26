"""Typed projections and commands for the authenticated approval console."""

from __future__ import annotations

from typing import Any

from .. import agentruns, approvals, store, summon, uistate


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
    linked = record.get("agent_run_id")
    if isinstance(linked, str) and linked:
        return linked
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


def _agent_labels() -> dict[str, tuple[str, str]]:
    """Summoned agent name -> (title, source), read once per request."""
    try:
        roster, _rejected = summon.load_roster()
    except OSError:
        return {}
    return {name: (spec.title, spec.source) for name, spec in roster.items()}


def _controls(run: dict[str, Any]) -> list[str]:
    """The control actions ``agentruns.control`` would accept right now."""
    if run.get("status") != "running":
        return []
    if run.get("control_state") == "blocked":
        return ["resume"]
    return ["steer", "abort"]


def _elapsed_seconds(run: dict[str, Any]) -> int:
    started = agentruns._age_seconds(run.get("started_at"))
    if run.get("status") == "running":
        return started
    # finish_run stamps last_heartbeat, so this is the run's own duration.
    return max(0, started - agentruns._age_seconds(run.get("last_heartbeat")))


def _summary(run: dict[str, Any], pending: int,
             labels: dict[str, tuple[str, str]]) -> dict[str, Any]:
    status = _status(run, pending)
    agent = run.get("agent")
    title, source = labels.get(str(agent or ""), (None, None))
    return {
        "id": run["id"],
        "parent_id": run.get("parent_id"),
        "agent": agent,
        "agent_title": title,
        "agent_source": source,
        "control_state": (
            "blocked" if run.get("control_state") == "blocked" else "active"),
        "controls": _controls(run),
        "elapsed_seconds": _elapsed_seconds(run),
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
    labels = _agent_labels()
    rows = [
        _summary(run, len(pending.get(run["id"], [])), labels)
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
    if run["stalled"]:
        # The same projection agentruns.list_runs applies, so the detail and
        # the listing agree on a run whose worker stopped reporting.
        run["status"] = "stale"
    detail = _summary(run, len(pending), _agent_labels())
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


def annotate_approvals(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Name the summoned run that raised each approval, when it still exists.

    Only an id that resolves to a durable run record is honoured, so a stray
    ``payload.run_id`` cannot label an approval with an agent that never ran.
    """
    labels: dict[str, tuple[str, str]] | None = None
    runs: dict[str, dict[str, Any] | None] = {}
    for item in items:
        run_id = _approval_run_id(item)
        if not run_id:
            continue
        if run_id not in runs:
            runs[run_id] = agentruns.get_run(run_id)
        run = runs[run_id]
        if run is None:
            continue
        if labels is None:
            labels = _agent_labels()
        agent = run.get("agent")
        title, source = labels.get(str(agent or ""), (None, None))
        item["agent_run"] = {
            "id": run["id"],
            "task": run.get("task", ""),
            "agent": agent,
            "agent_title": title,
            "agent_source": source,
        }
    return items


def agent_roster() -> dict[str, Any]:
    """The summonable specialists, without instructions, tools or paths."""
    try:
        roster, rejected = summon.load_roster()
    except OSError:
        return {"agents": [], "rejected_count": 0}
    specs = sorted(
        roster.values(), key=lambda spec: (spec.source != "builtin", spec.name))
    return {
        "agents": [
            {
                "name": spec.name,
                "title": spec.title,
                "description": spec.description,
                "source": spec.source,
                "max_turns": spec.max_turns,
            }
            for spec in specs
        ],
        "rejected_count": len(rejected),
    }


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
