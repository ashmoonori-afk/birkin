"""On-disk state shared between the daemon, Morpheus routine, and dashboard.

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
    # Unique per write so concurrent writers to the same path don't collide on
    # the temp file (pid + uuid covers both cross-thread and cross-process).
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
        try:  # restrict the temp file too, before it is briefly visible
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
    except OSError:
        try:  # don't leave a partial .tmp behind on a failed write
            tmp.unlink()
        except OSError:
            pass
        raise
    # State can include cron commands / pending payloads — restrict to the owner
    # (no-op on Windows; enforced on POSIX), matching config.json.
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


class file_lock:
    """A cross-process advisory lock for a read-modify-write on a shared JSON
    file (stdlib only: O_CREAT|O_EXCL spin, no fcntl/msvcrt so it works the
    same on Windows and POSIX).

    Guards files that TWO long-running processes mutate — cron.json is written
    by both `birkin gateway` (/remind) and the scheduler daemon (mark_ran) —
    where ``_write_json``'s atomic single write does not prevent a stale
    read-then-write from clobbering the other's change.

    A crashed holder's lock is reclaimed after ``stale`` seconds so a dead
    process can't wedge the file forever.
    """

    def __init__(self, path: Path, *, timeout: float = 5.0,
                 stale: float = 30.0):
        self._lock = Path(str(path) + ".lock")
        self._timeout = timeout
        self._stale = stale
        self._held = False

    def __enter__(self) -> "file_lock":
        import time
        deadline = time.monotonic() + self._timeout
        while True:
            try:
                fd = os.open(str(self._lock),
                             os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                self._held = True
                return self
            except FileExistsError:
                try:
                    age = time.time() - self._lock.stat().st_mtime
                    if age > self._stale:
                        self._lock.unlink()      # reclaim a crashed holder
                        continue
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    # Don't block a user command forever — proceed unlocked
                    # (the write is still individually atomic; we only lose
                    # the cross-process serialization in this rare case).
                    return self
                time.sleep(0.05)

    def __exit__(self, *exc: Any) -> None:
        if self._held:
            try:
                self._lock.unlink()
            except OSError:
                pass
            self._held = False

    @property
    def acquired(self) -> bool:
        return self._held


# -- usage estimation ------------------------------------------------------

def estimate_usage(*texts: str) -> dict[str, int]:
    """A cheap, dependency-free usage estimate: chars, words, and ~tokens
    (≈ chars/4). Not exact — a transparent heuristic for auditing/cost sense."""
    chars = sum(len(t or "") for t in texts)
    words = sum(len((t or "").split()) for t in texts)
    return {"chars": chars, "words": words, "estTokens": (chars + 3) // 4}


# -- run records + ledger --------------------------------------------------

def save_run(kind: str, summary: str, details: dict[str, Any] | None = None,
             usage: dict[str, int] | None = None) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    rid = f"{ts}-{uuid.uuid4().hex[:4]}"  # unique even within the same second
    rec = {"id": rid, "kind": kind, "at": _now(), "summary": summary,
           "usage": usage or {}, "details": details or {}}
    path = config.runs_dir() / f"{rid}-{kind}.json"
    _write_json(path, rec)
    append_ledger({"id": rid, "at": rec["at"], "kind": kind,
                   "summary": summary[:160], "usage": usage or {}})
    # Mirror into the SQLite event ledger (aggregatable; daemon/dashboard).
    from . import ledger
    u = usage or {}
    # estimate_usage() emits "estTokens"; older callers may pass "tokens".
    ledger.event(f"run:{kind}", summary,
                 tokens=int(u.get("tokens") or u.get("estTokens") or 0),
                 data={"id": rid})
    return path


def _is_run_record(record: Any) -> bool:
    if not isinstance(record, dict):
        return False
    strings = {key: record.get(key) for key in ("id", "kind", "at", "summary")}
    return all(isinstance(value, str) for value in strings.values()) and all(
        strings[key] for key in ("id", "kind", "at")
    )


def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    files = sorted(config.runs_dir().glob("*.json"), reverse=True)
    out: list[dict[str, Any]] = []
    if limit <= 0:
        return out
    for f in files:
        rec = _read_json(f, None)
        if _is_run_record(rec):
            out.append(rec)
            if len(out) == limit:
                break
    return out


def append_ledger(entry: dict[str, Any]) -> None:
    """Append one compact JSON line per run to ledger.jsonl (audit trail)."""
    try:
        with config.ledger_path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


# -- pending approvals -----------------------------------------------------

def add_pending(*, category: str, title: str, description: str,
                payload: dict[str, Any], origin: str = "morpheus") -> dict[str, Any]:
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


def valid_pending_id(aid: str) -> bool:
    return (isinstance(aid, str) and len(aid) == 12
            and all(char in "0123456789abcdef" for char in aid))


def get_pending(aid: str) -> dict[str, Any] | None:
    if not valid_pending_id(aid):
        return None
    return _read_json(config.pending_dir() / f"{aid}.json", None)


def resolve_pending(aid: str, status: str) -> dict[str, Any] | None:
    if not valid_pending_id(aid):
        return None
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


def is_status_stale(status: dict[str, Any], max_age_seconds: float = 120.0) -> bool:
    """A daemon whose heartbeat is older than ``max_age_seconds`` is considered
    stopped (a SIGKILL/crash leaves the on-disk flag set otherwise)."""
    hb = status.get("heartbeat")
    if not hb:
        return False  # no heartbeat recorded -> unknown, not stale
    try:
        t = datetime.fromisoformat(str(hb))
    except (ValueError, TypeError):
        return True
    now = datetime.now(timezone.utc)
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (now - t).total_seconds() > max_age_seconds


def clear_status() -> None:
    config.status_path().unlink(missing_ok=True)


# -- activity log ----------------------------------------------------------

def append_activity(line: str) -> None:
    try:
        with config.activity_log_path().open("a", encoding="utf-8") as fh:
            fh.write(f"{_now()}\t{line}\n")
    except OSError:
        pass  # activity logging must never break a chat turn


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
