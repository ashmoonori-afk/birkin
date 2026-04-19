"""Webhook trigger — fires when an HTTP request hits a specific path."""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Optional

from birkin.triggers.base import Trigger, TriggerConfig

logger = logging.getLogger(__name__)


class WebhookTrigger(Trigger):
    """Webhook-based trigger. Routes inbound HTTP requests to workflows.

    Unlike cron/file triggers, WebhookTrigger is passive — it doesn't
    poll. Instead, the triggers API router calls ``fire()`` when a
    matching webhook request arrives.

    Config keys:
        path: URL path suffix for this webhook (e.g. "deploy-notify").
        secret: Optional shared secret for verification.
    """

    def __init__(self, trigger_config: TriggerConfig) -> None:
        super().__init__(trigger_config)
        self._path: str = trigger_config.config.get("path", trigger_config.id)
        self._secret: Optional[str] = trigger_config.config.get("secret")
        self._running = False

    @property
    def path(self) -> str:
        return self._path

    @property
    def secret(self) -> Optional[str]:
        return self._secret

    async def start(self, on_fire: Callable[[TriggerConfig], Coroutine]) -> None:
        self._on_fire = on_fire
        self._running = True
        logger.info("WebhookTrigger %s registered at path: %s", self.id, self._path)

    async def stop(self) -> None:
        self._running = False
        logger.info("WebhookTrigger %s stopped", self.id)

    def is_running(self) -> bool:
        return self._running

    async def fire(self, payload: dict | None = None) -> bool:
        """Manually fire this trigger (called by the API router).

        Returns True if fired successfully.
        """
        if not self._running or not self._on_fire:
            return False
        logger.info("WebhookTrigger %s firing for workflow %s", self.id, self.workflow_id)
        await self._on_fire(self._config)
        return True
