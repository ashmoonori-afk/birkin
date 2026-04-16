"""Event store — SQLite-backed persistence for raw events."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from birkin.memory.events import RawEvent

logger = logging.getLogger(__name__)

_DEFAULT_DB = "birkin_events.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    provider TEXT,
    model TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    outcome TEXT NOT NULL DEFAULT 'success'
);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
"""


class EventStore:
    """Append-only SQLite event store for raw interaction events.

    Usage::

        store = EventStore("events.db")
        store.append(event)
        events = store.query(session_id="s1")
        recent = store.since("2026-04-16T00:00:00Z")
    """

    def __init__(self, db_path: Optional[str | Path] = None) -> None:
        self._db_path = str(db_path or _DEFAULT_DB)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def append(self, event: RawEvent) -> None:
        """Store a raw event."""
        tokens_in = event.tokens.tokens_in if event.tokens else 0
        tokens_out = event.tokens.tokens_out if event.tokens else 0
        cost_usd = event.tokens.cost_usd if event.tokens else 0.0

        self._conn.execute(
            "INSERT OR IGNORE INTO events "
            "(id, timestamp, session_id, event_type, provider, model, payload_json, tokens_in, tokens_out, cost_usd, outcome) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event.id,
                event.timestamp,
                event.session_id,
                event.event_type,
                event.provider,
                event.model,
                json.dumps(event.payload, default=str),
                tokens_in,
                tokens_out,
                cost_usd,
                event.outcome,
            ),
        )
        self._conn.commit()

    def query(
        self,
        session_id: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 100,
    ) -> list[RawEvent]:
        """Query events with optional filters."""
        conditions: list[str] = []
        params: list[str | int] = []

        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)
        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT id, timestamp, session_id, event_type, provider, model, payload_json, tokens_in, tokens_out, cost_usd, outcome FROM events {where} ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_event(r) for r in rows]

    def since(self, timestamp: str) -> list[RawEvent]:
        """Return all events since a given ISO timestamp."""
        rows = self._conn.execute(
            "SELECT id, timestamp, session_id, event_type, provider, model, payload_json, tokens_in, tokens_out, cost_usd, outcome "
            "FROM events WHERE timestamp >= ? ORDER BY timestamp",
            (timestamp,),
        ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def count(self, session_id: Optional[str] = None) -> int:
        """Count events, optionally filtered by session."""
        if session_id:
            row = self._conn.execute("SELECT COUNT(*) FROM events WHERE session_id = ?", (session_id,)).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) FROM events").fetchone()
        return row[0] if row else 0

    @staticmethod
    def _row_to_event(row: tuple) -> RawEvent:
        from birkin.memory.events import TokenUsageRecord

        return RawEvent(
            id=row[0],
            timestamp=row[1],
            session_id=row[2],
            event_type=row[3],
            provider=row[4],
            model=row[5],
            payload=json.loads(row[6]) if row[6] else {},
            tokens=TokenUsageRecord(tokens_in=row[7], tokens_out=row[8], cost_usd=row[9]),
            outcome=row[10],
        )

    def close(self) -> None:
        self._conn.close()
