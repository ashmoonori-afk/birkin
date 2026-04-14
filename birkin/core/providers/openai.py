"""OpenAI provider implementation.

TODO(BRA-59): Implement with:
- OpenAI Chat Completions API
- Streaming support
- Tool call handling
- Error handling + retries
"""

from __future__ import annotations

from typing import Any

from birkin.core.providers.base import Message, Provider, ProviderResponse

_DEFAULT_MODEL = "gpt-4o"


class OpenAIProvider(Provider):
    """OpenAI Chat Completions provider."""

    def __init__(self, *, model: str | None = None) -> None:
        self._model = model or _DEFAULT_MODEL

    @property
    def name(self) -> str:
        return "openai"

    @property
    def model(self) -> str:
        return self._model

    def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> ProviderResponse:
        raise NotImplementedError("OpenAI provider not yet implemented (BRA-59)")

    async def acomplete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> ProviderResponse:
        raise NotImplementedError("OpenAI provider not yet implemented (BRA-59)")
