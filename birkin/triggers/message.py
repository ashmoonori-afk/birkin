"""Message trigger — fires when an incoming message matches a filter."""

from __future__ import annotations

import logging
import re
from typing import Callable, Coroutine

from birkin.triggers.base import Trigger, TriggerConfig

logger = logging.getLogger(__name__)


class MessageTrigger(Trigger):
    """Fires when an incoming message (Telegram, Slack, etc.) matches a filter.

    Like WebhookTrigger, this is passive — the platform adapter calls
    ``check_and_fire()`` for each incoming message.

    Config keys:
        platform: Platform to match (e.g. "telegram", "slack", or "*" for any).
        patterns: List of regex patterns to match against message text.
        keywords: List of keywords for simple substring matching.
    """

    def __init__(self, trigger_config: TriggerConfig) -> None:
        super().__init__(trigger_config)
        self._platform: str = trigger_config.config.get("platform", "*")
        self._patterns: list[re.Pattern] = [
            re.compile(p, re.IGNORECASE) for p in trigger_config.config.get("patterns", [])
        ]
        self._keywords: list[str] = [k.lower() for k in trigger_config.config.get("keywords", [])]
        self._running = False

    @property
    def platform(self) -> str:
        return self._platform

    async def start(self, on_fire: Callable[[TriggerConfig], Coroutine]) -> None:
        self._on_fire = on_fire
        self._running = True
        logger.info("MessageTrigger %s started: platform=%s", self.id, self._platform)

    async def stop(self) -> None:
        self._running = False
        logger.info("MessageTrigger %s stopped", self.id)

    def is_running(self) -> bool:
        return self._running

    def matches(self, text: str, platform: str) -> bool:
        """Check if a message matches this trigger's filters."""
        if not self._running:
            return False

        # Platform filter
        if self._platform != "*" and self._platform != platform:
            return False

        # Pattern matching (regex)
        for pattern in self._patterns:
            if pattern.search(text):
                return True

        # Keyword matching (substring)
        text_lower = text.lower()
        for keyword in self._keywords:
            if keyword in text_lower:
                return True

        # No patterns/keywords = match everything for this platform
        if not self._patterns and not self._keywords:
            return True

        return False

    async def check_and_fire(self, text: str, platform: str) -> bool:
        """Check message and fire if it matches.

        Returns True if fired.
        """
        if not self.matches(text, platform):
            return False
        if self._on_fire:
            logger.info("MessageTrigger %s firing for workflow %s", self.id, self.workflow_id)
            await self._on_fire(self._config)
            return True
        return False
