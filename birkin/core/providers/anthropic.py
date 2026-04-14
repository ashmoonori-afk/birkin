"""Anthropic provider implementation.

TODO(BRA-59): Implement with:
- Anthropic Messages API
- Streaming support
- Tool use handling
- Error handling + retries
"""

from __future__ import annotations

from typing import Any

from birkin.core.providers.base import Message, Provider, ProviderResponse

_DEFAULT_MODEL = "claude-sonnet-4-6-20250414"


class AnthropicProvider(Provider):
    """Anthropic Messages API provider."""

    def __init__(self, *, model: str | None = None) -> None:
        self._model = model or _DEFAULT_MODEL

    @property
    def name(self) -> str:
        return "anthropic"

    @property
    def model(self) -> str:
        return self._model

    def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> ProviderResponse:
        raise NotImplementedError("Anthropic provider not yet implemented (BRA-59)")

    async def acomplete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> ProviderResponse:
        raise NotImplementedError("Anthropic provider not yet implemented (BRA-59)")
