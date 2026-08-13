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
  cfg_json      TEXT NOT NULL DEFAULT '{}',
  status        TEXT NOT NULL,
  started       TEXT NOT NULL,
  finished      TEXT,
  tokens        INTEGER NOT NULL DEFAULT 0,
  result_json   TEXT,
  parent_run_id TEXT,
  resume_action_id TEXT
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
  replayed_from_run_id TEXT,
  replayed_from_seq INTEGER,
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
CREATE TABLE IF NOT EXISTS input_waits (
  action_id             TEXT PRIMARY KEY,
  run_id                TEXT NOT NULL,
  worker_id             TEXT NOT NULL,
  step_id               TEXT NOT NULL,
  request_json          TEXT NOT NULL,
  question_digest       TEXT NOT NULL,
  expected_actor        TEXT NOT NULL,
  expected_capability   TEXT NOT NULL,
  expires_at            TEXT NOT NULL,
  resume_token          TEXT NOT NULL,
  input_schema_version  INTEGER NOT NULL,
  previous_state_digest TEXT NOT NULL,
  state                 TEXT NOT NULL,
  accepted_event_id     INTEGER,
  resume_run_id         TEXT,
  last_error            TEXT,
  created               TEXT NOT NULL,
  updated               TEXT NOT NULL,
  UNIQUE(run_id, worker_id, step_id)
);
CREATE TABLE IF NOT EXISTS accepted_answers (
  event_id               INTEGER PRIMARY KEY AUTOINCREMENT,
  action_id              TEXT NOT NULL UNIQUE,
  run_id                 TEXT NOT NULL,
  worker_id              TEXT NOT NULL,
  step_id                TEXT NOT NULL,
  question_digest        TEXT NOT NULL,
  actual_actor           TEXT NOT NULL,
  actual_capability      TEXT NOT NULL,
  expires_at             TEXT NOT NULL,
  resume_token_digest    TEXT NOT NULL,
  input_schema_version   INTEGER NOT NULL,
  previous_state_digest  TEXT NOT NULL,
  input_json             TEXT NOT NULL,
  accepted_at            TEXT NOT NULL,
  UNIQUE(run_id, worker_id, step_id)
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
    _add_columns(con, "runs", {
        "parent_run_id": "TEXT",
        "resume_action_id": "TEXT",
        "cfg_json": "TEXT NOT NULL DEFAULT '{}'",
    })
    _add_columns(con, "calls", {
        "traceback": "TEXT",
        "replayed_from_run_id": "TEXT",
        "replayed_from_seq": "INTEGER",
    })
    return con


def _add_columns(
    con: sqlite3.Connection,
    table: str,
    columns: dict[str, str],
) -> None:
    present = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
    for name, kind in columns.items():
        if name not in present:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")


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


class ContinuationJournalError(RuntimeError):
    """A durable continuation transition could not be committed."""


# -- run lifecycle ---------------------------------------------------------

def start_run(run_id: str, *, name: str, script_path: str,
              script_sha256: str, args: dict, bindings: dict,
              cfg: dict[str, Any] | None = None,
              parent_run_id: str | None = None,
              resume_action_id: str | None = None,
              critical: bool = False) -> None:
    try:
        with closing(_connect()) as con, con:
            con.execute(
                "INSERT OR REPLACE INTO runs (run_id, name, script_path, "
                "script_sha256, args_json, bindings_json, cfg_json, "
                "status, started, "
                "parent_run_id, resume_action_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'running', ?, ?, ?)",
                (run_id, name, str(script_path), script_sha256,
                 json.dumps(args, ensure_ascii=False),
                 json.dumps(bindings, ensure_ascii=False),
                 json.dumps(cfg or {}, ensure_ascii=False), _now(),
                 parent_run_id, resume_action_id))
    except Exception as exc:
        if critical:
            raise ContinuationJournalError(
                "could not start durable continuation child"
            ) from exc
        return
    if critical and get_run(run_id) is None:
        raise ContinuationJournalError(
            "continuation child start was not durable"
        )


def finish_run(run_id: str, status: str, *, result: Any = None,
               tokens: int = 0, critical: bool = False) -> None:
    try:
        with closing(_connect()) as con, con:
            con.execute(
                "UPDATE runs SET status = ?, finished = ?, result_json = ?, "
                "tokens = ? WHERE run_id = ?",
                (status, _now(),
                 json.dumps(result, ensure_ascii=False, default=str)
                 if result is not None else None,
                 int(tokens), run_id))
    except Exception as exc:
        if critical:
            raise ContinuationJournalError(
                "could not finish durable continuation child"
            ) from exc
        return
    if critical:
        stored = get_run(run_id)
        if stored is None or stored.get("status") != status:
            raise ContinuationJournalError(
                "continuation child finish was not durable"
            )


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


def record_cached_call(
    run_id: str,
    source: dict[str, Any],
) -> None:
    """Persist one replayed successful call in the child run."""
    with closing(_connect()) as con, con:
        con.execute(
            "INSERT INTO calls (run_id, seq, call_key, role, provider, model, "
            "label, phase, status, result, error, tokens, started, finished, "
            "traceback, replayed_from_run_id, replayed_from_seq) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ok', ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                int(source["seq"]),
                source["call_key"],
                source.get("role"),
                source.get("provider"),
                source.get("model"),
                source.get("label"),
                source.get("phase"),
                source.get("result") or "",
                source.get("error") or "",
                int(source.get("tokens") or 0),
                _now(),
                _now(),
                source.get("traceback") or "",
                source["run_id"],
                int(source["seq"]),
            ),
        )


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


# -- durable human input continuation --------------------------------------

def state_digest(run_id: str, worker_id: str, step_id: str) -> str:
    run = get_run(run_id)
    if run is None:
        raise ContinuationJournalError("continuation source run is missing")
    calls = run_calls(run_id)
    sequences = [int(call["seq"]) for call in calls]
    if sequences != list(range(1, len(sequences) + 1)):
        raise ContinuationJournalError("continuation call prefix is incomplete")
    if any(call["status"] != "ok" for call in calls):
        raise ContinuationJournalError("continuation call prefix is not durable")
    material = {
        "version": 1,
        "continuation_run_id": run_id,
        "worker_id": worker_id,
        "step_id": step_id,
        "script_sha256": run["script_sha256"],
        "script_path": run.get("script_path"),
        "cfg": json.loads(run.get("cfg_json") or "{}"),
        "args": json.loads(run.get("args_json") or "{}"),
        "bindings": json.loads(run.get("bindings_json") or "{}"),
        "calls": [
            {
                key: call.get(key)
                for key in (
                    "seq",
                    "call_key",
                    "role",
                    "provider",
                    "model",
                    "status",
                    "result",
                    "error",
                )
            }
            for call in calls
        ],
    }
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def create_input_wait(wait: dict[str, Any]) -> dict[str, Any]:
    stamp = _now()
    try:
        with closing(_connect()) as con, con:
            con.execute(
                "INSERT INTO input_waits (action_id, run_id, worker_id, "
                "step_id, request_json, question_digest, expected_actor, "
                "expected_capability, expires_at, resume_token, "
                "input_schema_version, previous_state_digest, state, created, "
                "updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                "'waiting', ?, ?)",
                (
                    wait["action_id"],
                    wait["run_id"],
                    wait["worker_id"],
                    wait["step_id"],
                    json.dumps(
                        wait["request"],
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    wait["question_digest"],
                    wait["expected_actor"],
                    wait["expected_capability"],
                    wait["expires_at"],
                    wait["resume_token"],
                    int(wait["input_schema_version"]),
                    wait["previous_state_digest"],
                    stamp,
                    stamp,
                ),
            )
    except (KeyError, TypeError, ValueError, sqlite3.Error) as exc:
        raise ContinuationJournalError(
            "could not persist continuation input wait"
        ) from exc
    stored = get_input_wait(str(wait["action_id"]))
    if stored is None:
        raise ContinuationJournalError("continuation input wait was not durable")
    return stored


def get_input_wait(action_id: str) -> dict[str, Any] | None:
    try:
        with closing(_connect()) as con, con:
            con.row_factory = sqlite3.Row
            row = con.execute(
                "SELECT * FROM input_waits WHERE action_id = ?",
                (action_id,),
            ).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["request"] = json.loads(result.pop("request_json"))
            return result
    except (json.JSONDecodeError, sqlite3.Error):
        return None


def get_accepted_answer(action_id: str) -> dict[str, Any] | None:
    try:
        with closing(_connect()) as con, con:
            con.row_factory = sqlite3.Row
            row = con.execute(
                "SELECT * FROM accepted_answers WHERE action_id = ?",
                (action_id,),
            ).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["input"] = json.loads(result.pop("input_json"))
            return result
    except (json.JSONDecodeError, sqlite3.Error):
        return None


def accept_input(
    action_id: str,
    *,
    actual_actor: str,
    actual_capability: str,
    resume_token: str,
    input_value: dict[str, Any],
) -> dict[str, Any]:
    """Atomically append one immutable answer and claim the waiting request."""
    stamp = _now()
    try:
        with closing(_connect()) as con:
            con.row_factory = sqlite3.Row
            con.execute("BEGIN IMMEDIATE")
            wait_row = con.execute(
                "SELECT * FROM input_waits WHERE action_id = ?",
                (action_id,),
            ).fetchone()
            if wait_row is None or wait_row["state"] != "waiting":
                raise ContinuationJournalError(
                    "continuation input is not waiting"
                )
            # Expiry is re-read under the write lock: validation happens before
            # this transaction and the lock itself can block for seconds.
            try:
                expires = datetime.fromisoformat(str(wait_row["expires_at"]))
            except ValueError as exc:
                raise ContinuationJournalError(
                    "continuation input expiry is invalid"
                ) from exc
            if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
                raise ContinuationJournalError("continuation input expired")
            token_digest = hashlib.sha256(
                resume_token.encode("utf-8")
            ).hexdigest()
            cursor = con.execute(
                "INSERT INTO accepted_answers (action_id, run_id, worker_id, "
                "step_id, question_digest, actual_actor, actual_capability, "
                "expires_at, resume_token_digest, input_schema_version, "
                "previous_state_digest, input_json, accepted_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    action_id,
                    wait_row["run_id"],
                    wait_row["worker_id"],
                    wait_row["step_id"],
                    wait_row["question_digest"],
                    actual_actor,
                    actual_capability,
                    wait_row["expires_at"],
                    token_digest,
                    int(wait_row["input_schema_version"]),
                    wait_row["previous_state_digest"],
                    json.dumps(
                        input_value,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    stamp,
                ),
            )
            con.execute(
                "UPDATE input_waits SET state = 'accepted', "
                "accepted_event_id = ?, updated = ? WHERE action_id = ?",
                (int(cursor.lastrowid), stamp, action_id),
            )
            con.commit()
    except sqlite3.IntegrityError as exc:
        raise ContinuationJournalError(
            "continuation input was already accepted"
        ) from exc
    except sqlite3.Error as exc:
        raise ContinuationJournalError(
            "could not accept continuation input"
        ) from exc
    event = get_accepted_answer(action_id)
    if event is None:
        raise ContinuationJournalError("accepted input event was not durable")
    return event


def claim_resume(action_id: str, resume_run_id: str) -> dict[str, Any]:
    stamp = _now()
    try:
        with closing(_connect()) as con, con:
            changed = con.execute(
                "UPDATE input_waits SET state = 'dispatching', "
                "resume_run_id = COALESCE(resume_run_id, ?), updated = ? "
                "WHERE action_id = ? AND state IN ('accepted', 'dispatching')",
                (resume_run_id, stamp, action_id),
            ).rowcount
    except sqlite3.Error as exc:
        raise ContinuationJournalError(
            "could not claim continuation resume"
        ) from exc
    wait = get_input_wait(action_id)
    if changed != 1 or wait is None:
        raise ContinuationJournalError("continuation resume is not claimable")
    return wait


def finish_resume(
    action_id: str,
    *,
    state: str,
    error: str = "",
) -> None:
    if state not in {"resumed", "error"}:
        raise ValueError("invalid continuation terminal state")
    try:
        with closing(_connect()) as con, con:
            changed = con.execute(
                "UPDATE input_waits SET state = ?, last_error = ?, "
                "updated = ? WHERE action_id = ? AND state = 'dispatching'",
                (state, error[:2000], _now(), action_id),
            ).rowcount
    except sqlite3.Error as exc:
        raise ContinuationJournalError(
            "could not finish continuation resume"
        ) from exc
    if changed != 1:
        raise ContinuationJournalError("continuation resume was not active")


def recoverable_inputs() -> list[dict[str, Any]]:
    try:
        with closing(_connect()) as con, con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT * FROM input_waits WHERE state IN "
                "('accepted', 'dispatching') ORDER BY created"
            )
            return [dict(row) for row in rows]
    except sqlite3.Error:
        return []


def waiting_inputs() -> list[dict[str, Any]]:
    try:
        with closing(_connect()) as con, con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT * FROM input_waits WHERE state = 'waiting' "
                "ORDER BY created"
            )
            result: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                item["request"] = json.loads(item.pop("request_json"))
                result.append(item)
            return result
    except (json.JSONDecodeError, sqlite3.Error):
        return []


def protected_run_ids() -> set[str]:
    try:
        with closing(_connect()) as con, con:
            rows = con.execute(
                "SELECT run_id, resume_run_id FROM input_waits "
                "WHERE state IN ('waiting', 'accepted', 'dispatching')"
            )
            return {
                value
                for row in rows
                for value in row
                if isinstance(value, str) and value
            }
    except sqlite3.Error:
        return set()


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
