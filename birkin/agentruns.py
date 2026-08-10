"""Durable registry and message inboxes for subagent runs."""

from __future__ import annotations

import contextlib
import contextvars
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from . import config
from .store import _read_json, _write_json, file_lock

TASK_MAX_CHARS = 500
RESULT_TAIL_CHARS = 4000
STALE_AFTER_SECONDS = 180
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
