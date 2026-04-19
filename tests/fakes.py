"""Shared test fakes for the Birkin test suite."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Optional

from birkin.core.models import Message
from birkin.core.providers.base import ModelCapabilities, Provider, ProviderResponse


class FakeProvider(Provider):
    """In-memory provider for testing."""

    def __init__(self, reply: str = "fake reply") -> None:
        self._reply = reply
        self.last_messages: list[Message] = []

    @property
    def name(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return "fake-v1"

    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(context_window=4096)

    def complete(
        self,
        messages: list[Message],
        *,
        tools: Optional[list[dict[str, Any]]] = None,
        stream_callback: Optional[Callable[[Optional[str]], None]] = None,
    ) -> ProviderResponse:
        self.last_messages = messages
        return ProviderResponse(
            content=self._reply,
            tool_calls=None,
            stop_reason="end_turn",
        )

    async def acomplete(
        self,
        messages: list[Message],
        *,
        tools: Optional[list[dict[str, Any]]] = None,
        stream_callback: Optional[Callable[[Optional[str]], None]] = None,
    ) -> ProviderResponse:
        return self.complete(messages, tools=tools, stream_callback=stream_callback)
