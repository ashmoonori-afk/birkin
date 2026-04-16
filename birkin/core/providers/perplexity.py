"""Perplexity provider — search-augmented LLM via OpenAI-compatible API."""

from __future__ import annotations

import os
from typing import Optional

from openai import AsyncOpenAI, OpenAI

from birkin.core.providers.base import ModelCapabilities, ProviderError, ProviderErrorKind
from birkin.core.providers.capabilities import Capability, ProviderProfile
from birkin.core.providers.openai_compat import OpenAICompatProvider

_DEFAULT_MODEL = "sonar-pro"
_BASE_URL = "https://api.perplexity.ai"

_MODEL_CAPS = {
    "sonar-pro": ModelCapabilities(context_window=200000, supports_tools=False),
    "sonar": ModelCapabilities(context_window=128000, supports_tools=False),
    "sonar-reasoning-pro": ModelCapabilities(context_window=128000, supports_tools=False),
    "sonar-reasoning": ModelCapabilities(context_window=128000, supports_tools=False),
}


class PerplexityProvider(OpenAICompatProvider):
    """Perplexity API provider. Specializes in search-augmented responses."""

    def __init__(self, *, model: Optional[str] = None, api_key: Optional[str] = None) -> None:
        self._model_str = model or _DEFAULT_MODEL
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
        return self._model_str

    def capabilities(self) -> ModelCapabilities:
        return _MODEL_CAPS.get(self._model_str, ModelCapabilities(context_window=128000, supports_tools=False))

    @property
    def profile(self) -> ProviderProfile:
        caps = self.capabilities()
        return ProviderProfile(
            name="perplexity",
            model=self._model_str,
            capabilities=frozenset({Capability.SEARCH, Capability.REASONING, Capability.LONG_CONTEXT}),
            cost_per_1k_input=1.0,
            cost_per_1k_output=5.0,
            max_context=caps.context_window,
            latency_tier="medium",
        )
