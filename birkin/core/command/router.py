"""Command router — dispatch parsed intents to handlers."""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Any, Optional

from pydantic import BaseModel

from birkin.core.command.parser import Intent

logger = logging.getLogger(__name__)


class CommandResult(BaseModel):
    """Result of dispatching a command."""

    success: bool
    output: str = ""
    intent_kind: str = ""
    error: Optional[str] = None


class CommandRouter:
    """Routes parsed intents to registered handlers.

    Usage::

        router = CommandRouter()
        router.register("run_workflow", my_workflow_handler)
        router.register("search", my_search_handler)

        result = await router.dispatch(intent)
    """

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[Intent], Coroutine[Any, Any, CommandResult]]] = {}

    def register(self, intent_kind: str, handler: Callable[[Intent], Coroutine[Any, Any, CommandResult]]) -> None:
        """Register a handler for an intent kind."""
        self._handlers[intent_kind] = handler

    async def dispatch(self, intent: Intent) -> CommandResult:
        """Dispatch an intent to its registered handler."""
        handler = self._handlers.get(intent.kind)
        if handler is None:
            # Fallback: try ask_agent handler for unknown intents
            fallback = self._handlers.get("ask_agent")
            if fallback is not None:
                return await fallback(intent)
            return CommandResult(
                success=False,
                intent_kind=intent.kind,
                error=f"No handler registered for intent: {intent.kind}",
            )

        try:
            result = await handler(intent)
            result.intent_kind = intent.kind
            return result
        except (OSError, RuntimeError, ValueError) as exc:
            logger.error("Command handler for %r failed: %s", intent.kind, exc)
            return CommandResult(
                success=False,
                intent_kind=intent.kind,
                error=str(exc),
            )

    @property
    def registered_kinds(self) -> list[str]:
        return list(self._handlers.keys())
