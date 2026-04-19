"""Trigger persistence — SQLite storage for trigger configs."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from birkin.triggers.base import TriggerConfig

_DEFAULT_DB = "birkin_sessions.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS triggers (
    id TEXT PRIMARY KEY,
    config_json TEXT NOT NULL,
    active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


class TriggerStore:
    """SQLite-backed persistence for trigger configurations.

    Supports use as a context manager::

        with TriggerStore() as store:
            store.save(config)
    """

    def __init__(self, db_path: Path | str = _DEFAULT_DB) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def __enter__(self) -> TriggerStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def save(self, config: TriggerConfig) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO triggers (id, config_json, active) VALUES (?, ?, ?)",
            (config.id, config.model_dump_json(), 1 if config.active else 0),
        )
        self._conn.commit()

    def remove(self, trigger_id: str) -> None:
        self._conn.execute("DELETE FROM triggers WHERE id = ?", (trigger_id,))
        self._conn.commit()

    def load_all_active(self) -> list[TriggerConfig]:
        rows = self._conn.execute("SELECT config_json FROM triggers WHERE active = 1").fetchall()
        return [TriggerConfig.model_validate_json(row[0]) for row in rows]

    def close(self) -> None:
        self._conn.close()
