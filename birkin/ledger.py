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
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config

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


def event(kind: str, summary: str = "", *, tokens: int = 0,
          data: dict[str, Any] | None = None) -> None:
    """Append one event. Never raises — the ledger must not break a run."""
    try:
        with closing(_connect()) as con, con:
            con.execute(
                "INSERT INTO events (ts, kind, summary, tokens, data) "
                "VALUES (?, ?, ?, ?, ?)",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 kind, summary[:200], int(tokens or 0),
                 json.dumps(data or {}, ensure_ascii=False)[:4000]))
    except Exception:
        pass


def usage(period: str = "day", now: datetime | None = None) -> int:
    """Total tokens recorded today / this month (UTC). period: day|month."""
    now = now or datetime.now(timezone.utc)
    prefix = now.strftime("%Y-%m-%d" if period == "day" else "%Y-%m")
    try:
        with closing(_connect()) as con, con:
            row = con.execute(
                "SELECT COALESCE(SUM(tokens), 0) FROM events WHERE ts LIKE ?",
                (prefix + "%",)).fetchone()
            return int(row[0])
    except Exception:
        return 0


def recent(limit: int = 50, kind: str | None = None) -> list[dict[str, Any]]:
    try:
        with closing(_connect()) as con, con:
            con.row_factory = sqlite3.Row
            if kind:
                rows = con.execute(
                    "SELECT ts, kind, summary, tokens FROM events "
                    "WHERE kind = ? ORDER BY id DESC LIMIT ?",
                    (kind, limit)).fetchall()
            else:
                rows = con.execute(
                    "SELECT ts, kind, summary, tokens FROM events "
                    "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []
