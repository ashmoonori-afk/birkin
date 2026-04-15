"""Message dispatcher for routing platform messages to the Birkin agent."""

from __future__ import annotations

import logging
from typing import Any, Optional

from birkin.core.agent import Agent
from birkin.core.providers import create_provider
from birkin.gateway.deps import get_session_store
from birkin.tools.loader import load_tools

logger = logging.getLogger(__name__)


class MessageDispatcher:
    """Routes messages from external platforms (Telegram, etc.) to the agent."""

    def __init__(self) -> None:
        """Initialize dispatcher."""
        self.session_store = get_session_store()
        self._cached_tools = None
        self._cached_provider_name = None

    def _load_tools(self) -> list[Any]:
        """Load tools (cached to avoid reloading)."""
        if self._cached_tools is None:
            self._cached_tools = load_tools()
        return self._cached_tools

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
        # Load or create session
        try:
            session = self.session_store.load(session_key)
            session_id = session.id
        except KeyError:
            # Create new session for this platform user
            session = self.session_store.create()
            # Store custom session key as title for lookup
            session.title = session_key
            self.session_store.save_session_metadata(session)
            session_id = session.id

        # Create provider and agent
        provider_instance = create_provider(provider, model=model)
        tools = self._load_tools()
        agent = Agent(
            provider=provider_instance,
            tools=tools,
            session_store=self.session_store,
            session_id=session_id,
        )

        try:
            # Run agent with message (async version)
            reply = await agent.achat(text)

            return reply
        except Exception as e:
            logger.error(f"Agent execution failed: {e}")
            raise
