"""Session persistence -- SQLite-backed.

TODO(BRA-58): Replace in-memory stubs with real SQLite storage:
- migrations / schema creation
- message append + retrieval with pagination
- session metadata (title, provider, model)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from birkin.core.providers.base import Message


@dataclass
class Session:
    """A conversation session."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    messages: list[Message] = field(default_factory=list)

    @property
    def message_count(self) -> int:
        return len(self.messages)

    def append(self, message: Message) -> None:
        self.messages.append(message)


class SessionStore:
    """Session store interface.

    Current implementation is in-memory only.
    BRA-58 will replace this with SQLite persistence.
    """

    def __init__(self, db_path: str = "birkin_sessions.db") -> None:
        self._db_path = db_path
        self._sessions: dict[str, Session] = {}

    def create(self) -> Session:
        session = Session()
        self._sessions[session.id] = session
        return session

    def load(self, session_id: str) -> Session:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"Session not found: {session_id}")
        return session

    def save(self, session: Session) -> None:
        self._sessions[session.id] = session

    def list_all(self) -> list[Session]:
        return sorted(self._sessions.values(), key=lambda s: s.created_at, reverse=True)

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
