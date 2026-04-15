"""Shared dependencies for gateway routes."""

from __future__ import annotations

from typing import Optional

from birkin.core.session import SessionStore

# Module-level singletons — initialised once when the app starts.
_session_store: Optional[SessionStore] = None


def get_session_store() -> SessionStore:
    """Return the global SessionStore, creating it lazily."""
    global _session_store  # noqa: PLW0603
    if _session_store is None:
        _session_store = SessionStore()
    return _session_store


def set_session_store(store: SessionStore) -> None:
    """Inject a custom SessionStore (useful for testing with :memory: db)."""
    global _session_store  # noqa: PLW0603
    _session_store = store


def reset_session_store() -> None:
    """Reset for testing — closes store and clears singleton."""
    global _session_store  # noqa: PLW0603
    if _session_store is not None:
        _session_store.close()
    _session_store = None
