"""Per-note process locks for serialized vault mutations."""

from __future__ import annotations

import threading

_NOTE_LOCKS: dict[str, threading.Lock] = {}
_NOTE_LOCKS_GUARD = threading.Lock()


def note_lock(note_slug: str) -> threading.Lock:
    """Return the process-local lock serializing one note's mutations."""
    with _NOTE_LOCKS_GUARD:
        lock = _NOTE_LOCKS.get(note_slug)
        if lock is None:
            lock = _NOTE_LOCKS[note_slug] = threading.Lock()
        return lock
