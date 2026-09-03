"""SQLite event ledger — the daemon's single queryable event stream.

One WAL-mode SQLite file (stdlib ``sqlite3``, keeping the zero-dependency
rule) under the birkin home. Every run, warm-session open/evict, and cron
fire lands here via :func:`event`; the budget tracker reads token usage with
:func:`usage` instead of scanning the JSON runs directory.

The JSON run records in ``store.py`` remain the human-readable audit trail;
the ledger is the *aggregatable* mirror (``store.save_run`` calls
:func:`event`). Writers never hold the connection across calls — one short
connection per event keeps cross-process use (gateway + scheduler) safe under
WAL.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from . import config

LedgerOperation = Literal["write", "query_usage", "query_recent"]
LedgerErrorCode = Literal[
    "permission_denied", "corrupt", "schema", "storage", "encoding"
]
LedgerBoundaryError = (
    sqlite3.Error | OSError | UnicodeError | TypeError | ValueError | OverflowError
)

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LedgerError(RuntimeError):
    """Typed storage diagnostic for an audit-ledger operation."""

    operation: LedgerOperation
    code: LedgerErrorCode
    path: Path
    detail: str

    def __str__(self) -> str:
        return (
            f"ledger {self.operation} failed [{self.code}] at "
            f"{self.path}: {self.detail}"
        )


@dataclass(frozen=True, slots=True)
class LedgerWriteResult:
    """Outcome of a best-effort ledger write."""

    ok: bool
    error: LedgerError | None = None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY,
    ts      TEXT NOT NULL,             -- UTC ISO seconds
    kind    TEXT NOT NULL,             -- run:chat | run:morpheus | run:cron |
                                       -- session:open | session:evict | ...
    summary TEXT NOT NULL DEFAULT '',
    tokens  INTEGER NOT NULL DEFAULT 0,
    data    TEXT NOT NULL DEFAULT '{}' -- JSON blob
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind);
"""


def _path() -> Path:
    return config.birkin_home() / "ledger.db"


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(_path(), timeout=5.0)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(_SCHEMA)
    return con


def _error(operation: LedgerOperation, exc: LedgerBoundaryError) -> LedgerError:
    detail = str(exc) or type(exc).__name__
    lowered = detail.lower()
    if isinstance(exc, PermissionError) or any(
        marker in lowered
        for marker in (
            "permission denied",
            "readonly database",
            "read-only database",
            "unable to open database file",
        )
    ):
        code: LedgerErrorCode = "permission_denied"
    elif isinstance(exc, sqlite3.DatabaseError) and any(
        marker in lowered
        for marker in (
            "malformed",
            "not a database",
            "file is encrypted",
        )
    ):
        code = "corrupt"
    elif isinstance(exc, sqlite3.DatabaseError) and any(
        marker in lowered
        for marker in (
            "no such table",
            "no such column",
            "has no column named",
            "database schema",
            "already exists",
        )
    ):
        code = "schema"
    elif isinstance(exc, (TypeError, ValueError, OverflowError, UnicodeError)):
        code = "encoding"
    else:
        code = "storage"
    return LedgerError(operation, code, _path(), detail[:500])


def event(
    kind: str, summary: str = "", *, tokens: int = 0, data: dict[str, Any] | None = None
) -> LedgerWriteResult:
    """Append one event without breaking the run that produced it.

    A failed mirror write returns a typed failure and logs it. It never raises
    and never warns: the ledger is a mirror, and ``-W error`` must not turn a
    locked database into a failed session.
    """
    try:
        token_count = int(tokens or 0)
        encoded_data = json.dumps(data or {}, ensure_ascii=False)[:4000]
    except (TypeError, ValueError, OverflowError, UnicodeError) as exc:
        error = _error("write", exc)
        _log.debug("%s", error)
        return LedgerWriteResult(ok=False, error=error)

    try:
        with closing(_connect()) as con, con:
            con.execute(
                "INSERT INTO events (ts, kind, summary, tokens, data) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    kind,
                    summary[:200],
                    token_count,
                    encoded_data,
                ),
            )
    except (sqlite3.Error, OSError, UnicodeError, OverflowError) as exc:
        error = _error("write", exc)
        _log.debug("%s", error)
        return LedgerWriteResult(ok=False, error=error)
    return LedgerWriteResult(ok=True)


def usage(period: str = "day", now: datetime | None = None) -> int:
    """Total tokens recorded today / this month (UTC). period: day|month.

    An unreadable ledger raises :class:`LedgerError`: a corrupt audit trail
    must never be indistinguishable from an empty one.
    """
    now = now or datetime.now(timezone.utc)
    prefix = now.strftime("%Y-%m-%d" if period == "day" else "%Y-%m")
    try:
        with closing(_connect()) as con, con:
            row = con.execute(
                "SELECT COALESCE(SUM(tokens), 0) FROM events WHERE ts LIKE ?",
                (prefix + "%",),
            ).fetchone()
    except (sqlite3.Error, OSError, UnicodeError) as exc:
        raise _error("query_usage", exc) from exc

    value = row[0]
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError, UnicodeError) as exc:
        raise _error("query_usage", exc) from exc


def recent(limit: int = 50, kind: str | None = None) -> list[dict[str, Any]]:
    """Most recent events, newest first; an unreadable ledger raises."""
    try:
        with closing(_connect()) as con, con:
            con.row_factory = sqlite3.Row
            if kind:
                rows = con.execute(
                    "SELECT ts, kind, summary, tokens FROM events "
                    "WHERE kind = ? ORDER BY id DESC LIMIT ?",
                    (kind, limit),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT ts, kind, summary, tokens FROM events "
                    "ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
    except (sqlite3.Error, OSError, UnicodeError, OverflowError) as exc:
        raise _error("query_recent", exc) from exc
    return [dict(row) for row in rows]
