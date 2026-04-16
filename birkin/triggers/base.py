"""Trigger abstraction — base class for all trigger types."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Any, Callable, Coroutine, Optional

from pydantic import BaseModel, Field


class TriggerConfig(BaseModel):
    """Serializable trigger configuration for persistence."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: str
    workflow_id: str
    active: bool = True
    config: dict[str, Any] = {}


class Trigger(ABC):
    """Abstract base class for workflow triggers.

    A trigger watches for a condition (time, file change, webhook, message)
    and fires a callback when the condition is met.
    """

    def __init__(self, trigger_config: TriggerConfig) -> None:
        self._config = trigger_config
        self._on_fire: Optional[Callable[[TriggerConfig], Coroutine]] = None

    @property
    def id(self) -> str:
        return self._config.id

    @property
    def workflow_id(self) -> str:
        return self._config.workflow_id

    @property
    def active(self) -> bool:
        return self._config.active

    @property
    def config(self) -> TriggerConfig:
        return self._config

    @property
    def trigger_type(self) -> str:
        return self._config.type

    @abstractmethod
    async def start(self, on_fire: Callable[[TriggerConfig], Coroutine]) -> None:
        """Start watching for the trigger condition.

        Args:
            on_fire: Async callback invoked when trigger fires.
        """
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop watching."""
        ...

    @abstractmethod
    def is_running(self) -> bool:
        """Check if the trigger is currently active and watching."""
        ...
