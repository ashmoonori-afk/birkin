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
        db_path = os.environ.get("BIRKIN_DB_PATH", "birkin_sessions.db")
        _session_store = SessionStore(db_path=db_path)
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
        _wiki_memory = WikiMemory(root=Path(os.environ.get("BIRKIN_MEMORY_DIR", "./memory")))
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


# ---------------------------------------------------------------------------
# SkillRegistry
# ---------------------------------------------------------------------------

_skill_registry = None


def get_skill_registry():
    """Return the global SkillRegistry, creating it lazily."""
    global _skill_registry  # noqa: PLW0603
    if _skill_registry is None:
        from birkin.skills.registry import SkillRegistry

        _skill_registry = SkillRegistry(skills_dir=Path("skills"))
        _skill_registry.load_all()
    return _skill_registry


def reset_skill_registry() -> None:
    """Reset for testing."""
    global _skill_registry  # noqa: PLW0603
    _skill_registry = None


# ---------------------------------------------------------------------------
# MCPRegistry
# ---------------------------------------------------------------------------

_mcp_registry = None


def get_mcp_registry():
    """Return the global MCPRegistry (sync — does not auto-connect servers)."""
    global _mcp_registry  # noqa: PLW0603
    if _mcp_registry is None:
        from birkin.mcp.registry import MCPRegistry

        _mcp_registry = MCPRegistry()
    return _mcp_registry


def reset_mcp_registry() -> None:
    """Reset for testing."""
    global _mcp_registry  # noqa: PLW0603
    _mcp_registry = None


# ---------------------------------------------------------------------------
# ProviderRouter
# ---------------------------------------------------------------------------

_provider_router = None


def get_provider_router():
    """Return the global ProviderRouter, auto-registering available providers."""
    global _provider_router  # noqa: PLW0603
    if _provider_router is None:
        from birkin.core.providers import create_provider
        from birkin.core.providers.registry import ProviderRegistry, ProviderRouter

        registry = ProviderRegistry()
        for name in ["anthropic", "openai", "perplexity", "gemini", "ollama", "groq", "claude-cli", "codex-cli"]:
            try:
                p = create_provider(f"{name}/default")
                registry.register(p)
            except (ValueError, TypeError, KeyError, Exception):
                pass  # provider not configured (no API key, etc.)
        _provider_router = ProviderRouter(registry)
    return _provider_router


def reset_provider_router() -> None:
    """Reset for testing."""
    global _provider_router  # noqa: PLW0603
    _provider_router = None


# ---------------------------------------------------------------------------
# InsightsEngine
# ---------------------------------------------------------------------------

_insights_engine = None
_insights_event_store = None


def get_insights_engine():
    """Return the global InsightsEngine, creating it lazily."""
    global _insights_engine, _insights_event_store  # noqa: PLW0603
    if _insights_engine is None:
        from birkin.memory.event_store import EventStore
        from birkin.memory.insights.engine import InsightsEngine

        _insights_event_store = EventStore()
        _insights_engine = InsightsEngine(_insights_event_store)
    return _insights_engine


def set_insights_engine(engine) -> None:
    """Inject a custom InsightsEngine (useful for testing)."""
    global _insights_engine  # noqa: PLW0603
    _insights_engine = engine


def reset_insights_engine() -> None:
    """Reset and close underlying EventStore."""
    global _insights_engine, _insights_event_store  # noqa: PLW0603
    if _insights_event_store is not None:
        try:
            _insights_event_store.close()
        except (OSError, AttributeError):
            pass
    _insights_event_store = None
    _insights_engine = None


# ---------------------------------------------------------------------------
# WorkflowRecommender
# ---------------------------------------------------------------------------

_workflow_recommender = None
_recommender_event_store = None


def get_workflow_recommender():
    """Return the global WorkflowRecommender, creating it lazily."""
    global _workflow_recommender, _recommender_event_store  # noqa: PLW0603
    if _workflow_recommender is None:
        from birkin.core.workflow.recommender import WorkflowRecommender
        from birkin.memory.event_store import EventStore

        _recommender_event_store = EventStore()
        _workflow_recommender = WorkflowRecommender(
            event_store=_recommender_event_store,
            wiki=get_wiki_memory(),
        )
    return _workflow_recommender


def set_workflow_recommender(recommender) -> None:
    """Inject a custom WorkflowRecommender (useful for testing)."""
    global _workflow_recommender  # noqa: PLW0603
    _workflow_recommender = recommender


def reset_workflow_recommender() -> None:
    """Reset and close underlying EventStore."""
    global _workflow_recommender, _recommender_event_store  # noqa: PLW0603
    if _recommender_event_store is not None:
        try:
            _recommender_event_store.close()
        except (OSError, AttributeError):
            pass
    _recommender_event_store = None
    _workflow_recommender = None
