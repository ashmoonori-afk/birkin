"""The workflow journal — what ran, what it cost in seconds, and what to skip.

Two jobs, one table set:

- **Resume.** Every agent call is keyed by (sequence, hash of prompt+options).
  Re-running the same script replays the recorded answers until the first key
  that differs, then goes live from there. Change one role's binding and only
  that role's calls miss.
- **Estimates.** The picker's "expected duration" and "budget footprint"
  signals are medians over this table, so they describe *this machine* rather
  than a vendor's price list, and they sharpen every time you run something.

WAL sqlite via stdlib, same shape as ledger.py / delivery.py: schema on
connect, one short-lived connection per write, writes never raise — a journal
that needs a clean shutdown to be trustworthy is not a journal.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import statistics
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .. import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id        TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  script_path   TEXT NOT NULL,
  script_sha256 TEXT NOT NULL,
  args_json     TEXT NOT NULL DEFAULT '{}',
  bindings_json TEXT NOT NULL DEFAULT '{}',
  status        TEXT NOT NULL,
  started       TEXT NOT NULL,
  finished      TEXT,
  tokens        INTEGER NOT NULL DEFAULT 0,
  result_json   TEXT
);
CREATE TABLE IF NOT EXISTS calls (
  run_id   TEXT NOT NULL,
  seq      INTEGER NOT NULL,
  call_key TEXT NOT NULL,
  role     TEXT,
  provider TEXT,
  model    TEXT,
  label    TEXT,
  phase    TEXT,
  status   TEXT NOT NULL,
  result   TEXT,
  error    TEXT,
  tokens   INTEGER NOT NULL DEFAULT 0,
  started  TEXT NOT NULL,
  finished TEXT,
  PRIMARY KEY (run_id, seq)
);
CREATE INDEX IF NOT EXISTS calls_by_model ON calls (provider, model, status);
CREATE TABLE IF NOT EXISTS incidents (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  kind            TEXT NOT NULL,
  channel         TEXT NOT NULL DEFAULT '',
  chat_id         TEXT NOT NULL DEFAULT '',
  elapsed_seconds REAL NOT NULL DEFAULT 0,
  partial_chars   INTEGER NOT NULL DEFAULT 0,
  last_event_kind TEXT NOT NULL DEFAULT '',
  event_count     INTEGER NOT NULL DEFAULT 0,
  detail          TEXT NOT NULL DEFAULT '',
  created         TEXT NOT NULL
);
"""


def _dir() -> Path:
    d = config.birkin_home() / "moirai"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path() -> Path:
    return _dir() / "moirai.db"


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(_path(), timeout=10.0)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(_SCHEMA)
    # A pre-existing moirai.db has no calls.traceback; CREATE TABLE IF NOT
    # EXISTS never adds a column, so every already-installed journal would
    # keep dropping the one field that makes a failure diagnosable.
    if "traceback" not in {row[1] for row in
                           con.execute("PRAGMA table_info(calls)")}:
        con.execute("ALTER TABLE calls ADD COLUMN traceback TEXT")
    return con


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def call_key(prompt: str, opts: dict[str, Any]) -> str:
    """Identity of one agent call: the prompt plus the options that change
    the answer. Label and phase are cosmetic and deliberately excluded, so
    renaming a step does not invalidate its cached result."""
    material = {k: opts.get(k) for k in
                ("provider", "model", "schema", "tools", "effort", "cwd",
                 "max_turns")}
    blob = json.dumps([prompt, material], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# -- run lifecycle ---------------------------------------------------------

def start_run(run_id: str, *, name: str, script_path: str,
              script_sha256: str, args: dict, bindings: dict) -> None:
    try:
        with closing(_connect()) as con, con:
            con.execute(
                "INSERT OR REPLACE INTO runs (run_id, name, script_path, "
                "script_sha256, args_json, bindings_json, status, started) "
                "VALUES (?, ?, ?, ?, ?, ?, 'running', ?)",
                (run_id, name, str(script_path), script_sha256,
                 json.dumps(args, ensure_ascii=False),
                 json.dumps(bindings, ensure_ascii=False), _now()))
    except Exception:
        pass


def finish_run(run_id: str, status: str, *, result: Any = None,
               tokens: int = 0) -> None:
    try:
        with closing(_connect()) as con, con:
            con.execute(
                "UPDATE runs SET status = ?, finished = ?, result_json = ?, "
                "tokens = ? WHERE run_id = ?",
                (status, _now(),
                 json.dumps(result, ensure_ascii=False, default=str)
                 if result is not None else None,
                 int(tokens), run_id))
    except Exception:
        pass


def get_run(run_id: str) -> Optional[dict]:
    try:
        with closing(_connect()) as con, con:
            con.row_factory = sqlite3.Row
            row = con.execute("SELECT * FROM runs WHERE run_id = ?",
                              (run_id,)).fetchone()
            return dict(row) if row else None
    except Exception:
        return None


def list_runs(limit: int = 20, name: Optional[str] = None) -> list[dict]:
    try:
        with closing(_connect()) as con, con:
            con.row_factory = sqlite3.Row
            if name:
                rows = con.execute(
                    "SELECT * FROM runs WHERE name = ? "
                    "ORDER BY started DESC LIMIT ?", (name, int(limit)))
            else:
                rows = con.execute(
                    "SELECT * FROM runs ORDER BY started DESC LIMIT ?",
                    (int(limit),))
            return [dict(r) for r in rows]
    except Exception:
        return []


def last_bindings(name: str) -> dict[str, str]:
    """What the previous run of this script used — the picker's '지난번'."""
    for run in list_runs(limit=10, name=name):
        try:
            data = json.loads(run.get("bindings_json") or "{}")
        except Exception:
            continue
        if data:
            return {str(k): str(v) for k, v in data.items()}
    return {}


# -- call lifecycle --------------------------------------------------------

def record_call(run_id: str, seq: int, key: str, *, role: str = "",
                provider: str = "", model: str = "", label: str = "",
                phase: str = "") -> None:
    try:
        with closing(_connect()) as con, con:
            con.execute(
                "INSERT OR REPLACE INTO calls (run_id, seq, call_key, role, "
                "provider, model, label, phase, status, started) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'running', ?)",
                (run_id, int(seq), key, role, provider, model, label, phase,
                 _now()))
    except Exception:
        pass


def finish_call(run_id: str, seq: int, *, status: str, result: str = "",
                error: str = "", tokens: int = 0,
                traceback: str = "") -> None:
    try:
        with closing(_connect()) as con, con:
            con.execute(
                "UPDATE calls SET status = ?, result = ?, error = ?, "
                "tokens = ?, finished = ?, traceback = ? "
                "WHERE run_id = ? AND seq = ?",
                (status, result, error, int(tokens), _now(),
                 traceback[:4000], run_id, int(seq)))
    except Exception:
        pass


def cached_calls(run_id: str) -> dict[int, dict]:
    """Successful calls from a prior run, by sequence — the resume source."""
    try:
        with closing(_connect()) as con, con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT * FROM calls WHERE run_id = ? AND status = 'ok' "
                "ORDER BY seq", (run_id,))
            return {int(r["seq"]): dict(r) for r in rows}
    except Exception:
        return {}


def run_calls(run_id: str) -> list[dict]:
    try:
        with closing(_connect()) as con, con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT * FROM calls WHERE run_id = ? ORDER BY seq", (run_id,))
            return [dict(r) for r in rows]
    except Exception:
        return []


def recent_failed_calls(limit: int = 10) -> list[dict]:
    try:
        with closing(_connect()) as con, con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT * FROM calls WHERE status = 'error' "
                "ORDER BY rowid DESC LIMIT ?", (int(limit),))
            return [dict(r) for r in rows]
    except sqlite3.Error:
        return []


# -- incidents (deaths that happen OUTSIDE a run) --------------------------

def record_incident(*, kind: str, channel: str = "", chat_id: str = "",
                    elapsed_seconds: float = 0.0, partial_chars: int = 0,
                    last_event_kind: str = "", event_count: int = 0,
                    detail: str = "") -> None:
    """One row for a turn that died without a workflow to blame.

    A 59-minute codex turn timed out and left NOTHING in this database — the
    only trace was a console line, so losing the terminal lost the evidence.
    """
    with closing(_connect()) as con, con:
        con.execute(
            "INSERT INTO incidents (kind, channel, chat_id, "
            "elapsed_seconds, partial_chars, last_event_kind, "
            "event_count, detail, created) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (kind, channel, str(chat_id), float(elapsed_seconds),
             int(partial_chars), last_event_kind, int(event_count),
             detail[:2000], _now()))


def recent_incidents(limit: int = 10) -> list[dict]:
    try:
        with closing(_connect()) as con, con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT * FROM incidents ORDER BY id DESC LIMIT ?",
                (int(limit),))
            return [dict(r) for r in rows]
    except sqlite3.Error:
        return []


def reclaim_stale_runs(exclude: Optional[set[str]] = None) -> int:
    """Close out runs a killed process left `running`, at boot.

    Without this a crashed run is indistinguishable from a live one, so the
    journal cannot answer "is it stuck or is it dead" — the exact question a
    59-minute silence raises. Anything still `running` when a process boots
    belongs to a process that is gone.
    """
    keep = set(exclude or ())
    stamp = _now()
    try:
        with closing(_connect()) as con, con:
            ids = [row[0] for row in
                   con.execute("SELECT run_id FROM runs WHERE "
                               "status = 'running'")
                   if row[0] not in keep]
            for run_id in ids:
                con.execute(
                    "UPDATE runs SET status = 'stale', finished = ? "
                    "WHERE run_id = ?", (stamp, run_id))
                con.execute(
                    "UPDATE calls SET status = 'stale', finished = ? "
                    "WHERE run_id = ? AND status = 'running'",
                    (stamp, run_id))
            return len(ids)
    except sqlite3.Error:
        return 0


# -- estimates (the picker's signals) --------------------------------------

def observed(provider: str, model: str) -> Optional[dict[str, float]]:
    """Median seconds and tokens for this (provider, model), from real runs.

    None when nothing has been recorded yet — the caller then falls back to a
    published measurement and marks the number as an estimate. Guessing
    silently would make the picker's most useful column its least trustworthy.
    """
    try:
        with closing(_connect()) as con, con:
            rows = con.execute(
                "SELECT started, finished, tokens FROM calls "
                "WHERE provider = ? AND model = ? AND status = 'ok' "
                "AND finished IS NOT NULL ORDER BY rowid DESC LIMIT 50",
                (provider, model)).fetchall()
    except Exception:
        return None
    seconds, tokens = [], []
    for started, finished, tok in rows:
        try:
            dt = (datetime.fromisoformat(finished)
                  - datetime.fromisoformat(started)).total_seconds()
        except Exception:
            continue
        if dt >= 0:
            seconds.append(dt)
            tokens.append(int(tok or 0))
    if not seconds:
        return None
    return {"seconds": statistics.median(seconds),
            "tokens": statistics.median(tokens) if tokens else 0.0,
            "n": float(len(seconds))}
