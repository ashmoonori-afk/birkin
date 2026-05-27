"""On-disk state shared between the daemon, nightly routine, and dashboard.

All JSON under the birkin home. Deliberately file-based (no DB) for the
local-first / transparent / zero-dependency principles. Readers (the dashboard)
and writers (the daemon) never hold locks across processes; writes are atomic
via a temp-file rename.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_json(path: Path, obj: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


# -- run summaries ---------------------------------------------------------

def save_run(kind: str, summary: str, details: dict[str, Any] | None = None) -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    rec = {"id": ts, "kind": kind, "at": _now(), "summary": summary,
           "details": details or {}}
    path = config.runs_dir() / f"{ts}-{kind}.json"
    _write_json(path, rec)
    return path


def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    files = sorted(config.runs_dir().glob("*.json"), reverse=True)
    out = []
    for f in files[:limit]:
        rec = _read_json(f, None)
        if rec:
            out.append(rec)
    return out


# -- pending approvals -----------------------------------------------------

def add_pending(*, category: str, title: str, description: str,
                payload: dict[str, Any], origin: str = "nightly") -> dict[str, Any]:
    aid = uuid.uuid4().hex[:12]
    rec = {"id": aid, "created": _now(), "category": category, "title": title,
           "description": description, "payload": payload, "origin": origin,
           "status": "pending"}
    _write_json(config.pending_dir() / f"{aid}.json", rec)
    return rec


def list_pending() -> list[dict[str, Any]]:
    out = []
    for f in sorted(config.pending_dir().glob("*.json")):
        rec = _read_json(f, None)
        if rec and rec.get("status") == "pending":
            out.append(rec)
    return out


def get_pending(aid: str) -> dict[str, Any] | None:
    return _read_json(config.pending_dir() / f"{aid}.json", None)


def resolve_pending(aid: str, status: str) -> dict[str, Any] | None:
    path = config.pending_dir() / f"{aid}.json"
    rec = _read_json(path, None)
    if not rec:
        return None
    rec["status"] = status
    rec["resolved_at"] = _now()
    _write_json(path, rec)
    return rec


# -- daemon status ---------------------------------------------------------

def write_status(status: dict[str, Any]) -> None:
    status = dict(status)
    status["heartbeat"] = _now()
    _write_json(config.status_path(), status)


def read_status() -> dict[str, Any]:
    return _read_json(config.status_path(), {"daemon": False})


def clear_status() -> None:
    config.status_path().unlink(missing_ok=True)


# -- activity log ----------------------------------------------------------

def append_activity(line: str) -> None:
    with config.activity_log_path().open("a", encoding="utf-8") as fh:
        fh.write(f"{_now()}\t{line}\n")


def read_recent_activity(hours: float = 24.0) -> str:
    path = config.activity_log_path()
    if not path.is_file():
        return ""
    cutoff = datetime.now(timezone.utc).timestamp() - hours * 3600
    out: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        ts, _, rest = line.partition("\t")
        try:
            t = datetime.fromisoformat(ts).timestamp()
        except ValueError:
            continue
        if t >= cutoff:
            out.append(rest)
    return "\n".join(out)
