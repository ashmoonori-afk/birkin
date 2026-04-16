"""SQLite-backed checkpointer for graph state persistence."""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Optional

from birkin.core.graph.checkpoint import Checkpointer, CheckpointMeta
from birkin.core.graph.state import ContextSnapshot

_DEFAULT_DB = "birkin_checkpoints.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    node_name TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    state_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_checkpoints_thread ON checkpoints(thread_id, timestamp);
"""


class SQLiteCheckpointer(Checkpointer):
    """Persists graph checkpoints to a local SQLite database.

    Usage::

        cp = SQLiteCheckpointer("checkpoints.db")
        cp_id = await cp.save("thread-1", snapshot)
        loaded = await cp.load(cp_id)
    """

    def __init__(self, db_path: Optional[str | Path] = None) -> None:
        self._db_path = str(db_path or _DEFAULT_DB)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    async def save(self, thread_id: str, snapshot: ContextSnapshot) -> str:
        checkpoint_id = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO checkpoints (checkpoint_id, thread_id, node_name, timestamp, state_json, metadata_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                checkpoint_id,
                thread_id,
                snapshot.node_name,
                snapshot.timestamp,
                json.dumps(snapshot.state, default=str),
                json.dumps(snapshot.metadata, default=str),
            ),
        )
        self._conn.commit()
        return checkpoint_id

    async def load(self, checkpoint_id: str) -> ContextSnapshot:
        row = self._conn.execute(
            "SELECT node_name, timestamp, state_json, metadata_json FROM checkpoints WHERE checkpoint_id = ?",
            (checkpoint_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"Checkpoint not found: {checkpoint_id}")
        return ContextSnapshot(
            node_name=row[0],
            timestamp=row[1],
            state=json.loads(row[2]),
            metadata=json.loads(row[3]),
        )

    async def list_thread(self, thread_id: str) -> list[CheckpointMeta]:
        rows = self._conn.execute(
            "SELECT checkpoint_id, thread_id, node_name, timestamp FROM checkpoints "
            "WHERE thread_id = ? ORDER BY timestamp",
            (thread_id,),
        ).fetchall()
        return [
            CheckpointMeta(
                checkpoint_id=r[0],
                thread_id=r[1],
                node_name=r[2],
                timestamp=r[3],
            )
            for r in rows
        ]

    def close(self) -> None:
        self._conn.close()
