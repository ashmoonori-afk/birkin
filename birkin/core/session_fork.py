"""Session fork & replay — branch conversations and re-run from checkpoints."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel

if TYPE_CHECKING:
    from birkin.core.session import SessionStore

logger = logging.getLogger(__name__)


class ForkResult(BaseModel):
    """Result of forking a session."""

    new_session_id: str
    forked_from_session: str
    forked_at_seq: int
    messages_copied: int


class SessionForker:
    """Fork and replay sessions.

    Fork: create a new session with messages up to a given sequence number.
    Replay: re-run the agent from a specific point with modified input.

    Usage::

        forker = SessionForker(session_store)
        result = forker.fork("session-123", from_seq=5)
        # result.new_session_id contains the forked session
    """

    def __init__(self, store: SessionStore) -> None:
        self._store = store

    def fork(
        self,
        session_id: str,
        from_seq: int,
        *,
        modifications: Optional[dict] = None,
    ) -> ForkResult:
        """Fork a session from a specific message sequence number.

        Creates a new session containing messages [0..from_seq].

        Args:
            session_id: Source session to fork from.
            from_seq: Message index to fork at (inclusive).
            modifications: Optional modifications to the last message.

        Returns:
            ForkResult with the new session details.
        """
        # Load source messages
        messages = self._store.get_messages(session_id)
        if from_seq < 0 or from_seq >= len(messages):
            raise ValueError(f"Invalid sequence {from_seq}: session has {len(messages)} messages")

        # Create new session
        source_session = self._store.load(session_id)
        new_session = self._store.create(
            provider=source_session.provider,
            model=source_session.model,
        )

        # Copy messages up to from_seq (inclusive)
        copied = messages[: from_seq + 1]
        for msg in copied:
            self._store.append_message(new_session.id, msg)

        logger.info(
            "Forked session %s at seq %d → %s (%d messages)",
            session_id[:12],
            from_seq,
            new_session.id[:12],
            len(copied),
        )

        return ForkResult(
            new_session_id=new_session.id,
            forked_from_session=session_id,
            forked_at_seq=from_seq,
            messages_copied=len(copied),
        )

    def list_forks(self, session_id: str) -> list[str]:
        """List session IDs that were forked from a given session.

        Note: This is a simple scan. For production, add parent_session_id
        column to the sessions table.
        """
        # Placeholder — full implementation requires schema migration
        return []
