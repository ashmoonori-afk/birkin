"""Session persistence backed by SQLite with WAL mode."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional, Union

from birkin.core.models import Message

logger = logging.getLogger(__name__)


@dataclass
class Session:
    """A conversation session with metadata."""

    id: str
    created_at: datetime
    title: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None

    @classmethod
    def new(
        cls,
        *,
        title: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Session:
        """Create a new session."""
        return cls(
            id=uuid.uuid4().hex[:12],
            created_at=datetime.now(UTC),
            title=title,
            provider=provider,
            model=model,
        )


class SessionStore:
    """SQLite-backed session store with thread-safe access via WAL mode."""

    def __init__(self, db_path: Union[str, Path] = "birkin_sessions.db") -> None:
        self._db_path = Path(db_path)
        self._local = threading.local()
        self._all_connections: list[sqlite3.Connection] = []
        self._conn_lock = threading.Lock()
        self._init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local SQLite connection."""
        if not hasattr(self._local, "connection") or self._local.connection is None:
            conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            # Enable WAL mode for better concurrency
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            self._local.connection = conn
            with self._conn_lock:
                self._all_connections.append(conn)
        return self._local.connection

    def _init_schema(self) -> None:
        """Initialize database schema."""
        conn = self._get_connection()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                title TEXT,
                provider TEXT,
                model TEXT
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                tool_calls TEXT,
                tool_call_id TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id),
                UNIQUE(session_id, seq)
            );

            CREATE INDEX IF NOT EXISTS idx_messages_session_seq
                ON messages(session_id, seq);
        """)
        conn.commit()

    def create(
        self,
        *,
        title: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Session:
        """Create a new session."""
        session = Session.new(title=title, provider=provider, model=model)
        conn = self._get_connection()
        conn.execute(
            """
            INSERT INTO sessions (id, created_at, title, provider, model)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                session.id,
                session.created_at.isoformat(),
                session.title,
                session.provider,
                session.model,
            ),
        )
        conn.commit()
        return session

    def load(self, session_id: str) -> Session:
        """Load a session by ID."""
        conn = self._get_connection()
        row = conn.execute(
            "SELECT id, created_at, title, provider, model FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()

        if row is None:
            raise KeyError(f"Session not found: {session_id}")

        return Session(
            id=row["id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            title=row["title"],
            provider=row["provider"],
            model=row["model"],
        )

    def save_session_metadata(self, session: Session) -> None:
        """Update session metadata."""
        conn = self._get_connection()
        conn.execute(
            """
            UPDATE sessions
            SET title = ?, provider = ?, model = ?
            WHERE id = ?
            """,
            (session.title, session.provider, session.model, session.id),
        )
        conn.commit()

    def append_message(self, session_id: str, message: Message) -> None:
        """Append a message to a session."""
        conn = self._get_connection()
        # Get the next sequence number
        row = conn.execute(
            "SELECT MAX(seq) as max_seq FROM messages WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        max_seq = row["max_seq"]
        seq = (max_seq + 1) if max_seq is not None else 0

        conn.execute(
            """
            INSERT INTO messages
            (session_id, seq, role, content, tool_calls, tool_call_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                seq,
                message.role,
                message.content,
                json.dumps(message.tool_calls) if message.tool_calls else None,
                message.tool_call_id,
                datetime.now(UTC).isoformat(),
            ),
        )
        conn.commit()

    def get_messages(self, session_id: str, limit: Optional[int] = None, offset: int = 0) -> list[Message]:
        """Retrieve messages from a session with pagination."""
        conn = self._get_connection()
        query = """
            SELECT role, content, tool_calls, tool_call_id
            FROM messages
            WHERE session_id = ?
            ORDER BY seq ASC
        """
        params = [session_id]

        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        messages = []
        for row in rows:
            tool_calls = None
            if row["tool_calls"]:
                tool_calls = json.loads(row["tool_calls"])

            messages.append(
                Message(
                    role=row["role"],
                    content=row["content"],
                    tool_calls=tool_calls,
                    tool_call_id=row["tool_call_id"],
                )
            )

        return messages

    def get_message_count(self, session_id: str) -> int:
        """Get the number of messages in a session."""
        conn = self._get_connection()
        row = conn.execute(
            "SELECT COUNT(*) as count FROM messages WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return row["count"]

    def list_sessions(self, limit: int = 50) -> list[Session]:
        """List all sessions, ordered by creation date (newest first)."""
        conn = self._get_connection()
        rows = conn.execute(
            """
            SELECT id, created_at, title, provider, model
            FROM sessions
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        return [
            Session(
                id=row["id"],
                created_at=datetime.fromisoformat(row["created_at"]),
                title=row["title"],
                provider=row["provider"],
                model=row["model"],
            )
            for row in rows
        ]

    def delete_session(self, session_id: str) -> None:
        """Delete a session and all its messages."""
        conn = self._get_connection()
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()

    def close(self) -> None:
        """Close the current thread's database connection."""
        if hasattr(self._local, "connection") and self._local.connection:
            self._local.connection.close()
            self._local.connection = None

    def close_all(self) -> None:
        """Close all tracked database connections across all threads."""
        with self._conn_lock:
            for conn in self._all_connections:
                try:
                    conn.close()
                except sqlite3.Error:
                    logger.debug("Failed to close SQLite connection", exc_info=True)
            self._all_connections.clear()
        # Also clear the thread-local reference if present
        if hasattr(self._local, "connection"):
            self._local.connection = None
