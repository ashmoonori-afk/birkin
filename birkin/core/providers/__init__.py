"""LLM provider abstraction layer."""

from __future__ import annotations

from birkin.core.providers.base import Message, Provider, ProviderResponse

__all__ = ["Message", "Provider", "ProviderResponse", "create_provider"]


def create_provider(name: str, *, model: str | None = None) -> Provider:
    """Factory — instantiate a provider by name."""
    if name == "openai":
        from birkin.core.providers.openai import OpenAIProvider

        return OpenAIProvider(model=model)
    if name == "anthropic":
        from birkin.core.providers.anthropic import AnthropicProvider

        return AnthropicProvider(model=model)
    raise ValueError(f"Unknown provider: {name!r}. Choose 'openai' or 'anthropic'.")
