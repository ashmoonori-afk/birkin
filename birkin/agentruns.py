"""Durable registry and message inboxes for subagent runs."""

from __future__ import annotations

import contextlib
import contextvars
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from . import config
from .store import _read_json, _write_json, file_lock

TASK_MAX_CHARS = 500
RESULT_TAIL_CHARS = 4000
STALE_AFTER_SECONDS = 180
# A bounded progress trail is what makes /attach an attach rather than a record
# dump: sequence numbers (not list positions) survive the trail rotating.
EVENT_TRAIL_MAX = 40
EVENT_TEXT_MAX = 200
FOLLOW_INTERVAL_SECONDS = 0.5
_STATUSES = {"running", "done", "error", "stale"}
_active_run_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "birkin_active_agent_run", default=None)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _valid_id(run_id: str) -> bool:
    return (isinstance(run_id, str) and len(run_id) == 12
            and all(char in "0123456789abcdef" for char in run_id))


def _record_path(run_id: str) -> Path:
    return config.agent_runs_dir() / f"{run_id}.json"


def _age_seconds(value: Any) -> int:
    try:
        stamp = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return STALE_AFTER_SECONDS + 1
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return max(0, int((datetime.now(timezone.utc) - stamp).total_seconds()))


def _is_record(value: Any) -> bool:
    if not isinstance(value, dict) or not _valid_id(value.get("id")):
        return False
    return (value.get("status") in _STATUSES
            and isinstance(value.get("task"), str)
            and isinstance(value.get("started_at"), str)
            and isinstance(value.get("last_heartbeat"), str))


def register_run(task: str, parent_id: str | None = None) -> dict[str, Any]:
    """Create and persist a running record, returning a copy of it."""
    run_id = uuid.uuid4().hex[:12]
    now = _now()
    rec: dict[str, Any] = {
        "id": run_id,
        "parent_id": parent_id if parent_id is not None else _active_run_id.get(),
        "task": str(task or "")[:TASK_MAX_CHARS],
        "status": "running",
        "started_at": now,
        "last_heartbeat": now,
        "result": "",
    }
    _write_json(_record_path(run_id), rec)
    return dict(rec)


def get_run(run_id: str) -> dict[str, Any] | None:
    """Read one run, or return None for an invalid, missing, or corrupt record."""
    if not _valid_id(run_id):
        return None
    rec = _read_json(_record_path(run_id), None)
    return dict(rec) if _is_record(rec) else None


def _update(run_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
    if not _valid_id(run_id):
        return None
    path = _record_path(run_id)
    with file_lock(path):
        rec = _read_json(path, None)
        if not _is_record(rec):
            return None
        rec.update(changes)
        _write_json(path, rec)
    return dict(rec)


def heartbeat(run_id: str) -> dict[str, Any] | None:
    """Refresh a run's heartbeat without changing its lifecycle status."""
    return _update(run_id, {"last_heartbeat": _now()})


def _next_seq(events: list[Any]) -> int:
    highest = 0
    for event in events:
        seq = event.get("seq") if isinstance(event, dict) else None
        if isinstance(seq, int) and not isinstance(seq, bool):
            highest = max(highest, seq)
    return highest + 1


def progress(run_id: str, text: str) -> dict[str, Any] | None:
    """Append one bounded progress line and refresh the heartbeat in one write."""
    if not _valid_id(run_id):
        return None
    line = " ".join(str(text or "").split())[:EVENT_TEXT_MAX]
    path = _record_path(run_id)
    with file_lock(path):
        rec = _read_json(path, None)
        if not _is_record(rec):
            return None
        raw = rec.get("events")
        events = list(raw) if isinstance(raw, list) else []
        if line:
            events.append({"seq": _next_seq(events), "at": _now(), "text": line})
            events = events[-EVENT_TRAIL_MAX:]
        rec.update(last_heartbeat=_now(), events=events)
        _write_json(path, rec)
    return dict(rec)


def events_after(rec: dict[str, Any], seq: int) -> list[dict[str, Any]]:
    """Progress entries of ``rec`` newer than ``seq``, oldest first."""
    raw = rec.get("events")
    if not isinstance(raw, list):
        return []
    fresh = [event for event in raw
             if isinstance(event, dict)
             and isinstance(event.get("seq"), int)
             and not isinstance(event.get("seq"), bool)
             and event["seq"] > seq]
    return sorted(fresh, key=lambda event: event["seq"])


def follow(run_id: str, on_line: Callable[[str], None], *,
           interval: float = FOLLOW_INTERVAL_SECONDS,
           sleep: Callable[[float], None] | None = None,
           ) -> dict[str, Any] | None:
    """Stream a run's new progress lines until it stops running.

    Returns the final record, ``None`` if the run is gone. A run whose heartbeat
    has gone stale ends the follow rather than blocking on a dead worker, and a
    finished run returns immediately after replaying its trail.
    """
    wait = sleep if sleep is not None else time.sleep
    seen = 0
    while True:
        rec = get_run(run_id)
        if rec is None:
            return None
        for event in events_after(rec, seen):
            seen = event["seq"]
            on_line(str(event.get("text") or ""))
        if rec.get("status") != "running":
            return rec
        if _age_seconds(rec.get("last_heartbeat")) > STALE_AFTER_SECONDS:
            return rec
        wait(interval)


def finish_run(run_id: str, status: str, result: str = "") -> dict[str, Any] | None:
    """Finalize a run as done/error/stale and retain only the result tail."""
    if status not in _STATUSES - {"running"}:
        raise ValueError(f"invalid agent run status: {status!r}")
    return _update(run_id, {
        "status": status,
        "last_heartbeat": _now(),
        "result": str(result or "")[-RESULT_TAIL_CHARS:],
    })


def list_runs() -> list[dict[str, Any]]:
    """Return all valid records as roots with nested ``children`` lists.

    A running record whose heartbeat is older than 180 seconds is presented as
    stale without rewriting its durable lifecycle record. Orphans are roots so
    a deleted/corrupt parent never hides a run.
    """
    records: list[dict[str, Any]] = []
    for path in config.agent_runs_dir().glob("*.json"):
        rec = _read_json(path, None)
        if not _is_record(rec):
            continue
        item = dict(rec)
        age = _age_seconds(item["last_heartbeat"])
        stalled = item["status"] == "running" and age > STALE_AFTER_SECONDS
        if stalled:
            item["status"] = "stale"
        item.update(heartbeat_age=age, stalled=stalled, children=[])
        records.append(item)

    records.sort(key=lambda run: (run["started_at"], run["id"]))
    by_id = {run["id"]: run for run in records}
    roots: list[dict[str, Any]] = []
    for run in records:
        parent = by_id.get(run.get("parent_id"))
        if parent is None or parent is run:
            roots.append(run)
        else:
            parent["children"].append(run)
    return roots


def control(run_id: str, action: str, text: str = "") -> dict[str, Any] | None:
    """Persist a console control command after validating its state transition.

    ``abort`` blocks delivery at the next worker boundary rather than deleting
    the run, so a remote operator can explicitly resume it. Workers continue to
    use the existing inbox authority for steering messages.
    """
    if not _valid_id(run_id):
        return None
    path = _record_path(run_id)
    with file_lock(path):
        rec = _read_json(path, None)
        if not _is_record(rec):
            return None
        if rec["status"] != "running":
            return {"ok": False, "error": "run is already finished"}
        blocked = rec.get("control_state") == "blocked"
        if action == "steer":
            if blocked:
                return {"ok": False, "error": "blocked run must be resumed first"}
            if not text.strip():
                return {"ok": False, "error": "steer text is required"}
        elif action == "abort":
            if blocked:
                return {"ok": False, "error": "run is already blocked"}
            rec["control_state"] = "blocked"
        elif action == "resume":
            if not blocked:
                return {"ok": False, "error": "only a blocked run can resume"}
            rec["control_state"] = "active"
        else:
            return {"ok": False, "error": "unknown control action"}
        rec["last_control"] = {"action": action, "at": _now()}
        _write_json(path, rec)
    if action == "steer" and not append_message(run_id, text.strip()[:TASK_MAX_CHARS]):
        return {"ok": False, "error": "could not queue steer message"}
    return {"ok": True, "record": dict(rec)}


def append_message(run_id: str, text: str) -> bool:
    """Atomically append one message file to a run's inbox."""
    if not _valid_id(run_id) or not isinstance(text, str) or not text:
        return False
    inbox = config.agent_runs_dir() / f"{run_id}.inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    name = f"{time.time_ns():020d}-{uuid.uuid4().hex[:8]}.json"
    _write_json(inbox / name, {"text": text})
    return True


def drain_messages(run_id: str) -> list[str]:
    """Return queued messages in order and delete every consumed file."""
    if not _valid_id(run_id):
        return []
    inbox = config.agent_runs_dir() / f"{run_id}.inbox"
    if not inbox.is_dir():
        return []
    lock_path = inbox / ".drain"
    messages: list[str] = []
    with file_lock(lock_path):
        for path in sorted(inbox.glob("*.json")):
            payload = _read_json(path, None)
            if isinstance(payload, dict) and isinstance(payload.get("text"), str):
                messages.append(payload["text"])
            try:
                path.unlink()
            except OSError:
                pass
    return messages


@contextlib.contextmanager
def _run_scope(run_id: str) -> Iterator[None]:
    """Make nested registrations children of ``run_id`` in this context."""
    token = _active_run_id.set(run_id)
    try:
        yield
    finally:
        _active_run_id.reset(token)
