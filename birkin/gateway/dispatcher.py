"""Message dispatcher for routing platform messages to the Birkin agent."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from birkin.core.agent import Agent
from birkin.core.providers import create_provider
from birkin.gateway.deps import get_session_store, get_wiki_memory
from birkin.tools.loader import load_tools

logger = logging.getLogger(__name__)


class MessageDispatcher:
    """Routes messages from external platforms (Telegram, etc.) to the agent."""

    def __init__(self) -> None:
        """Initialize dispatcher."""
        self.session_store = get_session_store()
        self._cached_tools: Optional[list[Any]] = None

    def _load_tools(self) -> list[Any]:
        """Load tools (cached to avoid reloading)."""
        if self._cached_tools is None:
            self._cached_tools = load_tools()
        return self._cached_tools

    def _find_session_by_key(self, session_key: str) -> Optional[str]:
        """Find a session ID by its platform key (stored as title).

        Returns the session ID if found, None otherwise.
        """
        sessions = self.session_store.list_sessions(limit=200)
        for s in sessions:
            if s.title == session_key:
                return s.id
        return None

    async def dispatch_message(
        self,
        text: str,
        session_key: str,
        provider: str = "anthropic",
        model: Optional[str] = None,
    ) -> str:
        """Process a message and return the agent's response.

        Args:
            text: User message text.
            session_key: Unique identifier for the session/user
                        (e.g., "telegram_123456789").
            provider: LLM provider name (default: "anthropic").
            model: Optional model override.

        Returns:
            Agent's response text.

        Raises:
            Exception: If agent execution fails.
        """
        # Look up existing session by platform key (stored as title)
        session_id = self._find_session_by_key(session_key)

        if session_id is None:
            # Create new session for this platform user
            session = self.session_store.create(
                title=session_key,
                provider=provider,
            )
            session_id = session.id

        # Load config once and apply overrides
        try:
            from birkin.gateway.config import load_config

            config = load_config()
            if config.get("provider"):
                provider = config["provider"]
            if config.get("model"):
                model = config["model"]
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            logger.warning("Failed to load gateway config (%s), using defaults", exc)
            config = {}

        # Create provider and agent
        model_str = f"{provider}/{model}" if model else f"{provider}/default"
        provider_instance = create_provider(model_str)
        tools = self._load_tools()

        agent_kwargs: dict[str, Any] = {
            "provider": provider_instance,
            "tools": tools,
            "session_store": self.session_store,
            "session_id": session_id,
            "memory": get_wiki_memory(),
        }

        # Apply system prompt from config
        if config.get("system_prompt"):
            agent_kwargs["system_prompt"] = config["system_prompt"]

        agent = Agent(**agent_kwargs)

        try:
            reply = await agent.achat(text)
            return reply
        except (ConnectionError, TimeoutError, RuntimeError, TypeError, ValueError) as e:
            logger.error("Agent execution failed: %s", e)
            raise
