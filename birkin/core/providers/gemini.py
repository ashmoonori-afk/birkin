"""Google Gemini provider — multimodal LLM via OpenAI-compatible API."""

from __future__ import annotations

import os
from typing import Optional

from openai import AsyncOpenAI, OpenAI

from birkin.core.providers.base import ModelCapabilities, ProviderError, ProviderErrorKind
from birkin.core.providers.capabilities import Capability, ProviderProfile
from birkin.core.providers.openai_compat import OpenAICompatProvider

_DEFAULT_MODEL = "gemini-2.5-flash"
_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

_MODEL_CAPS = {
    "gemini-2.5-pro": ModelCapabilities(context_window=1000000, supports_vision=True),
    "gemini-2.5-flash": ModelCapabilities(context_window=1000000, supports_vision=True),
    "gemini-2.0-flash": ModelCapabilities(context_window=1000000, supports_vision=True),
}


class GeminiProvider(OpenAICompatProvider):
    """Google Gemini API provider (OpenAI-compatible endpoint)."""

    def __init__(self, *, model: Optional[str] = None, api_key: Optional[str] = None) -> None:
        self._model_str = model or _DEFAULT_MODEL
        api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ProviderError("GEMINI_API_KEY not set", ProviderErrorKind.AUTH)
        self._client = OpenAI(api_key=api_key, base_url=_BASE_URL)
        self._async_client = AsyncOpenAI(api_key=api_key, base_url=_BASE_URL)

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def model(self) -> str:
        return self._model_str

    def capabilities(self) -> ModelCapabilities:
        return _MODEL_CAPS.get(self._model_str, ModelCapabilities(context_window=1000000, supports_vision=True))

    @property
    def profile(self) -> ProviderProfile:
        caps = self.capabilities()
        return ProviderProfile(
            name="gemini",
            model=self._model_str,
            capabilities=frozenset(
                {
                    Capability.REASONING,
                    Capability.CODE,
                    Capability.VISION,
                    Capability.LONG_CONTEXT,
                    Capability.TOOL_USE,
                    Capability.STRUCTURED_OUTPUT,
                }
            ),
            cost_per_1k_input=0.15 if "flash" in self._model_str else 1.25,
            cost_per_1k_output=0.60 if "flash" in self._model_str else 10.0,
            max_context=caps.context_window,
            latency_tier="low" if "flash" in self._model_str else "medium",
        )
