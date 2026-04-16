"""Groq provider — ultra low-latency LLM via OpenAI-compatible API."""

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

_DEFAULT_MODEL = "llama-3.3-70b-versatile"
_BASE_URL = "https://api.groq.com/openai/v1"

_MODEL_CAPS = {
    "llama-3.3-70b-versatile": ModelCapabilities(context_window=128000),
    "llama-3.1-8b-instant": ModelCapabilities(context_window=128000),
    "gemma2-9b-it": ModelCapabilities(context_window=8192),
    "mixtral-8x7b-32768": ModelCapabilities(context_window=32768),
}


class GroqProvider(Provider):
    """Groq API provider (OpenAI-compatible). Optimized for ultra low-latency inference."""

    def __init__(self, *, model: Optional[str] = None, api_key: Optional[str] = None) -> None:
        self._model = model or _DEFAULT_MODEL
        api_key = api_key or os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ProviderError("GROQ_API_KEY not set", ProviderErrorKind.AUTH)
        self._client = OpenAI(api_key=api_key, base_url=_BASE_URL)
        self._async_client = AsyncOpenAI(api_key=api_key, base_url=_BASE_URL)

    @property
    def name(self) -> str:
        return "groq"

    @property
    def model(self) -> str:
        return self._model

    def capabilities(self) -> ModelCapabilities:
        return _MODEL_CAPS.get(self._model, ModelCapabilities(context_window=128000))

    @property
    def profile(self) -> ProviderProfile:
        caps = self.capabilities()
        return ProviderProfile(
            name="groq",
            model=self._model,
            capabilities=frozenset(
                {
                    Capability.REASONING,
                    Capability.CODE,
                    Capability.LOW_LATENCY,
                    Capability.TOOL_USE,
                }
            ),
            cost_per_1k_input=0.59,
            cost_per_1k_output=0.79,
            max_context=caps.context_window,
            latency_tier="low",
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
