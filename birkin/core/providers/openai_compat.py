"""OpenAI-compatible provider base class.

Shared implementation for providers that use the OpenAI SDK:
Perplexity, Gemini, Ollama, Groq, and any future compatible provider.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from openai import AsyncOpenAI, OpenAI

from birkin.core.models import Message
from birkin.core.providers.base import (
    Provider,
    ProviderError,
    ProviderErrorKind,
    ProviderResponse,
    TokenUsage,
)


class OpenAICompatProvider(Provider):
    """Base class for providers using the OpenAI-compatible chat completions API.

    Subclasses must set ``_client``, ``_async_client``, ``_model_str``
    in ``__init__``, and implement ``name``, ``model``, ``capabilities``,
    and ``profile``.
    """

    _client: OpenAI
    _async_client: AsyncOpenAI
    _model_str: str

    def _build_messages(self, messages: list[Message]) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        for m in messages:
            if m.role == "tool":
                continue
            result.append({"role": m.role, "content": m.content})
        return result

    def _parse_usage(self, usage: Any) -> Optional[TokenUsage]:
        if usage is None:
            return None
        return TokenUsage(
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
        )

    def complete(
        self,
        messages: list[Message],
        *,
        tools: Optional[list[dict[str, Any]]] = None,
        stream_callback: Optional[Callable[[Optional[str]], None]] = None,
    ) -> ProviderResponse:
        try:
            response = self._client.chat.completions.create(
                model=self._model_str,
                messages=self._build_messages(messages),
            )
            choice = response.choices[0]
            return ProviderResponse(
                content=choice.message.content,
                usage=self._parse_usage(response.usage),
                model=response.model,
            )
        except Exception as exc:
            if _is_openai_api_error(exc):
                raise ProviderError(str(exc), ProviderErrorKind.API) from exc
            raise

    async def acomplete(
        self,
        messages: list[Message],
        *,
        tools: Optional[list[dict[str, Any]]] = None,
        stream_callback: Optional[Callable[[Optional[str]], None]] = None,
    ) -> ProviderResponse:
        try:
            response = await self._async_client.chat.completions.create(
                model=self._model_str,
                messages=self._build_messages(messages),
            )
            choice = response.choices[0]
            return ProviderResponse(
                content=choice.message.content,
                usage=self._parse_usage(response.usage),
                model=response.model,
            )
        except Exception as exc:
            if _is_openai_api_error(exc):
                raise ProviderError(str(exc), ProviderErrorKind.API) from exc
            raise


def _is_openai_api_error(exc: BaseException) -> bool:
    """Check if an exception is an OpenAI API error (not a programming bug)."""
    try:
        from openai import APIError

        return isinstance(exc, APIError)
    except ImportError:
        return isinstance(exc, (ConnectionError, TimeoutError, OSError))
