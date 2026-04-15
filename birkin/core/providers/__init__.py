"""LLM provider abstraction layer with Anthropic and OpenAI implementations."""

from __future__ import annotations

from typing import Optional

from birkin.core.providers.anthropic import AnthropicProvider
from birkin.core.providers.base import (
    ModelCapabilities,
    Provider,
    ProviderError,
    ProviderErrorKind,
    ProviderResponse,
    TokenUsage,
)
from birkin.core.providers.openai import OpenAIProvider

__all__ = [
    "Provider",
    "ProviderResponse",
    "ProviderError",
    "ProviderErrorKind",
    "TokenUsage",
    "ModelCapabilities",
    "AnthropicProvider",
    "OpenAIProvider",
    "create_provider",
]


def create_provider(
    model: str,
    *,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Provider:
    """Factory function to create a provider based on model ID.

    Model ID format:
    - "anthropic/claude-opus-4" -> AnthropicProvider
    - "openai/gpt-4o" -> OpenAIProvider
    - "openrouter/model-name" -> OpenAIProvider with OpenRouter

    Args:
        model: Model identifier string.
        api_key: Optional API key override.
        base_url: Optional base URL override.

    Returns:
        Appropriate Provider instance.

    Raises:
        ValueError: If model format is unsupported.
    """
    if "/" in model:
        provider_name, model_name = model.split("/", 1)
    else:
        # Default to OpenAI for backward compatibility
        provider_name = "openai"
        model_name = model

    if provider_name == "anthropic":
        return AnthropicProvider(model=model_name, api_key=api_key)
    elif provider_name == "openai":
        return OpenAIProvider(model=model_name, api_key=api_key, base_url=base_url)
    elif provider_name == "openrouter":
        return OpenAIProvider(
            model=f"openrouter/{model_name}",
            api_key=api_key,
            base_url=base_url or "https://openrouter.ai/api/v1",
        )
    else:
        raise ValueError(
            f"Unknown provider: {provider_name}. "
            "Use 'anthropic', 'openai', or 'openrouter'."
        )
