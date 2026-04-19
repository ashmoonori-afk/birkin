"""Trigger scheduler — manages active triggers and their lifecycle."""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Optional

from birkin.triggers.base import Trigger, TriggerConfig

logger = logging.getLogger(__name__)


class TriggerScheduler:
    """Manages active triggers: start, stop, list, persist.

    Usage::

        scheduler = TriggerScheduler()
        scheduler.register_type("cron", CronTrigger)
        await scheduler.add(config, on_fire_callback)
        await scheduler.remove(trigger_id)
        await scheduler.shutdown()
    """

    def __init__(self) -> None:
        self._triggers: dict[str, Trigger] = {}
        self._types: dict[str, type[Trigger]] = {}
        self._on_fire: Optional[Callable[[TriggerConfig], Coroutine]] = None

    def register_type(self, name: str, trigger_class: type[Trigger]) -> None:
        """Register a trigger type (e.g. 'cron' -> CronTrigger)."""
        self._types[name] = trigger_class

    def set_default_callback(self, callback: Callable[[TriggerConfig], Coroutine]) -> None:
        """Set the default on_fire callback for all triggers."""
        self._on_fire = callback

    async def add(
        self,
        config: TriggerConfig,
        on_fire: Optional[Callable[[TriggerConfig], Coroutine]] = None,
    ) -> Trigger:
        """Create and start a trigger from config.

        Args:
            config: Trigger configuration.
            on_fire: Callback when trigger fires. Falls back to default.

        Returns:
            The started Trigger instance.

        Raises:
            ValueError: If trigger type is unknown or trigger ID already exists.
        """
        if config.id in self._triggers:
            raise ValueError(f"Trigger already exists: {config.id}")

        trigger_class = self._types.get(config.type)
        if trigger_class is None:
            raise ValueError(f"Unknown trigger type: {config.type!r}. Registered: {list(self._types.keys())}")

        callback = on_fire or self._on_fire
        if callback is None:
            raise ValueError("No on_fire callback provided and no default set")

        trigger = trigger_class(config)
        if config.active:
            await trigger.start(callback)

        self._triggers[config.id] = trigger
        logger.info("Trigger %s (%s) added for workflow %s", config.id, config.type, config.workflow_id)
        return trigger

    async def remove(self, trigger_id: str) -> bool:
        """Stop and remove a trigger. Returns True if found."""
        trigger = self._triggers.pop(trigger_id, None)
        if trigger is None:
            return False
        if trigger.is_running():
            await trigger.stop()
        logger.info("Trigger %s removed", trigger_id)
        return True

    async def start_trigger(self, trigger_id: str) -> bool:
        """Start a stopped trigger."""
        trigger = self._triggers.get(trigger_id)
        if trigger is None:
            return False
        callback = self._on_fire
        if callback and not trigger.is_running():
            await trigger.start(callback)
        return True

    async def stop_trigger(self, trigger_id: str) -> bool:
        """Stop a running trigger without removing it."""
        trigger = self._triggers.get(trigger_id)
        if trigger is None:
            return False
        if trigger.is_running():
            await trigger.stop()
        return True

    def get(self, trigger_id: str) -> Optional[Trigger]:
        """Look up a trigger by ID."""
        return self._triggers.get(trigger_id)

    def list_all(self) -> list[Trigger]:
        """Return all registered triggers."""
        return list(self._triggers.values())

    def list_configs(self) -> list[TriggerConfig]:
        """Return configs for all triggers (for persistence/API)."""
        return [t.config for t in self._triggers.values()]

    async def shutdown(self) -> None:
        """Stop all triggers."""
        for trigger_id in list(self._triggers.keys()):
            await self.remove(trigger_id)
        logger.info("TriggerScheduler shutdown complete")

    def __len__(self) -> int:
        return len(self._triggers)

    def __repr__(self) -> str:
        running = sum(1 for t in self._triggers.values() if t.is_running())
        return f"TriggerScheduler({len(self)} triggers, {running} running)"
