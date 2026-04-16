"""Ollama provider — fully local LLM via OpenAI-compatible API."""

from __future__ import annotations

import os
from typing import Optional

from openai import AsyncOpenAI, OpenAI

from birkin.core.providers.base import ModelCapabilities
from birkin.core.providers.capabilities import Capability, ProviderProfile
from birkin.core.providers.openai_compat import OpenAICompatProvider

_DEFAULT_MODEL = "llama3.1"
_DEFAULT_BASE_URL = "http://localhost:11434/v1"


class OllamaProvider(OpenAICompatProvider):
    """Ollama local LLM provider. Zero API key needed."""

    def __init__(self, *, model: Optional[str] = None, base_url: Optional[str] = None) -> None:
        self._model_str = model or _DEFAULT_MODEL
        base_url = base_url or os.getenv("OLLAMA_BASE_URL", _DEFAULT_BASE_URL)
        self._client = OpenAI(api_key="ollama", base_url=base_url)
        self._async_client = AsyncOpenAI(api_key="ollama", base_url=base_url)

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def model(self) -> str:
        return self._model_str

    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(context_window=128000, supports_tools=False, supports_streaming=True)

    @property
    def profile(self) -> ProviderProfile:
        return ProviderProfile(
            name="ollama",
            model=self._model_str,
            capabilities=frozenset({Capability.REASONING, Capability.CODE}),
            cost_per_1k_input=0.0,
            cost_per_1k_output=0.0,
            max_context=128000,
            latency_tier="high",
            local=True,
        )
