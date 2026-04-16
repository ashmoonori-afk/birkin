"""Ollama provider — fully local LLM via OpenAI-compatible API."""

from __future__ import annotations

import os
from typing import Any, Callable, Optional

from openai import AsyncOpenAI, OpenAI

from birkin.core.models import Message
from birkin.core.providers.base import (
    ModelCapabilities,
    Provider,
    ProviderError,
    ProviderErrorKind,
    ProviderResponse,
    TokenUsage,
)
from birkin.core.providers.capabilities import Capability, ProviderProfile

_DEFAULT_MODEL = "llama3.1"
_DEFAULT_BASE_URL = "http://localhost:11434/v1"


class OllamaProvider(Provider):
    """Ollama local LLM provider (OpenAI-compatible API).

    Requires Ollama running locally. Zero API key needed.
    """

    def __init__(
        self,
        *,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        self._model = model or _DEFAULT_MODEL
        base_url = base_url or os.getenv("OLLAMA_BASE_URL", _DEFAULT_BASE_URL)
        # Ollama doesn't need a real API key but openai SDK requires one
        self._client = OpenAI(api_key="ollama", base_url=base_url)
        self._async_client = AsyncOpenAI(api_key="ollama", base_url=base_url)

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def model(self) -> str:
        return self._model

    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            context_window=128000,
            supports_tools=False,
            supports_streaming=True,
        )

    @property
    def profile(self) -> ProviderProfile:
        return ProviderProfile(
            name="ollama",
            model=self._model,
            capabilities=frozenset({Capability.REASONING, Capability.CODE}),
            cost_per_1k_input=0.0,
            cost_per_1k_output=0.0,
            max_context=128000,
            latency_tier="high",
            local=True,
        )

    def _build_messages(self, messages: list[Message]) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        for m in messages:
            if m.role == "tool":
                continue
            result.append({"role": m.role, "content": m.content})
        return result

    def complete(
        self,
        messages: list[Message],
        *,
        tools: Optional[list[dict[str, Any]]] = None,
        stream_callback: Optional[Callable[[Optional[str]], None]] = None,
    ) -> ProviderResponse:
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=self._build_messages(messages),
            )
            choice = response.choices[0]
            usage = None
            if response.usage:
                usage = TokenUsage(
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                )
            return ProviderResponse(
                content=choice.message.content,
                usage=usage,
                model=response.model,
            )
        except Exception as exc:
            raise ProviderError(str(exc), ProviderErrorKind.API) from exc

    async def acomplete(
        self,
        messages: list[Message],
        *,
        tools: Optional[list[dict[str, Any]]] = None,
        stream_callback: Optional[Callable[[Optional[str]], None]] = None,
    ) -> ProviderResponse:
        try:
            response = await self._async_client.chat.completions.create(
                model=self._model,
                messages=self._build_messages(messages),
            )
            choice = response.choices[0]
            usage = None
            if response.usage:
                usage = TokenUsage(
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                )
            return ProviderResponse(
                content=choice.message.content,
                usage=usage,
                model=response.model,
            )
        except Exception as exc:
            raise ProviderError(str(exc), ProviderErrorKind.API) from exc
