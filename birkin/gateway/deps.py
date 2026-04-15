"""Shared dependencies for gateway routes.

All gateway singletons are managed here with get/set/reset accessors
so they can be injected during testing.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from birkin.core.session import SessionStore
from birkin.memory.wiki import WikiMemory

if TYPE_CHECKING:
    from birkin.gateway.dispatcher import MessageDispatcher
    from birkin.gateway.platforms.telegram_adapter import TelegramAdapter

# ---------------------------------------------------------------------------
# SessionStore
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# WikiMemory
# ---------------------------------------------------------------------------

_wiki_memory: Optional[WikiMemory] = None


def get_wiki_memory() -> WikiMemory:
    """Return the global WikiMemory, creating it lazily."""
    global _wiki_memory  # noqa: PLW0603
    if _wiki_memory is None:
        _wiki_memory = WikiMemory(root=Path("./memory"))
        _wiki_memory.init()
    return _wiki_memory


def set_wiki_memory(wiki: WikiMemory) -> None:
    """Inject a custom WikiMemory (useful for testing)."""
    global _wiki_memory  # noqa: PLW0603
    _wiki_memory = wiki


def reset_wiki_memory() -> None:
    """Reset for testing — clears singleton."""
    global _wiki_memory  # noqa: PLW0603
    _wiki_memory = None


# ---------------------------------------------------------------------------
# TelegramAdapter
# ---------------------------------------------------------------------------

_telegram_adapter: Optional[TelegramAdapter] = None


def get_telegram_adapter() -> TelegramAdapter:
    """Return the global TelegramAdapter, creating it lazily."""
    global _telegram_adapter  # noqa: PLW0603
    if _telegram_adapter is None:
        from birkin.gateway.platforms.telegram_adapter import TelegramAdapter

        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN not set")
        _telegram_adapter = TelegramAdapter(token)
    return _telegram_adapter


def set_telegram_adapter(adapter: TelegramAdapter) -> None:
    """Inject a custom TelegramAdapter."""
    global _telegram_adapter  # noqa: PLW0603
    _telegram_adapter = adapter


def reset_telegram_adapter() -> None:
    """Reset for testing."""
    global _telegram_adapter  # noqa: PLW0603
    _telegram_adapter = None


# ---------------------------------------------------------------------------
# MessageDispatcher
# ---------------------------------------------------------------------------

_dispatcher: Optional[MessageDispatcher] = None


def get_dispatcher() -> MessageDispatcher:
    """Return the global MessageDispatcher, creating it lazily."""
    global _dispatcher  # noqa: PLW0603
    if _dispatcher is None:
        from birkin.gateway.dispatcher import MessageDispatcher

        _dispatcher = MessageDispatcher()
    return _dispatcher


def set_dispatcher(dispatcher: MessageDispatcher) -> None:
    """Inject a custom MessageDispatcher."""
    global _dispatcher  # noqa: PLW0603
    _dispatcher = dispatcher


def reset_dispatcher() -> None:
    """Reset for testing."""
    global _dispatcher  # noqa: PLW0603
    _dispatcher = None
