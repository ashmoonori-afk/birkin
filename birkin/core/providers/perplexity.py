"""Perplexity provider — search-augmented LLM via OpenAI-compatible API."""

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

_DEFAULT_MODEL = "sonar-pro"
_BASE_URL = "https://api.perplexity.ai"

_MODEL_CAPS = {
    "sonar-pro": ModelCapabilities(context_window=200000, supports_tools=False),
    "sonar": ModelCapabilities(context_window=128000, supports_tools=False),
    "sonar-reasoning-pro": ModelCapabilities(context_window=128000, supports_tools=False),
    "sonar-reasoning": ModelCapabilities(context_window=128000, supports_tools=False),
}


class PerplexityProvider(Provider):
    """Perplexity API provider (OpenAI-compatible). Specializes in search-augmented responses."""

    def __init__(self, *, model: Optional[str] = None, api_key: Optional[str] = None) -> None:
        self._model = model or _DEFAULT_MODEL
        api_key = api_key or os.getenv("PERPLEXITY_API_KEY")
        if not api_key:
            raise ProviderError("PERPLEXITY_API_KEY not set", ProviderErrorKind.AUTH)
        self._client = OpenAI(api_key=api_key, base_url=_BASE_URL)
        self._async_client = AsyncOpenAI(api_key=api_key, base_url=_BASE_URL)

    @property
    def name(self) -> str:
        return "perplexity"

    @property
    def model(self) -> str:
        return self._model

    def capabilities(self) -> ModelCapabilities:
        return _MODEL_CAPS.get(self._model, ModelCapabilities(context_window=128000, supports_tools=False))

    @property
    def profile(self) -> ProviderProfile:
        caps = self.capabilities()
        return ProviderProfile(
            name="perplexity",
            model=self._model,
            capabilities=frozenset({Capability.SEARCH, Capability.REASONING, Capability.LONG_CONTEXT}),
            cost_per_1k_input=1.0,
            cost_per_1k_output=5.0,
            max_context=caps.context_window,
            latency_tier="medium",
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
