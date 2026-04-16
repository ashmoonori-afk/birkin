"""Provider registry and router — discover and select providers by capability."""

from __future__ import annotations

import logging
from typing import Optional

from birkin.core.providers.base import Provider
from birkin.core.providers.capabilities import Capability, ProviderProfile

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """Manages available providers and supports querying by capability.

    Usage::

        registry = ProviderRegistry()
        registry.register(anthropic_provider)
        registry.register(perplexity_provider)

        search_providers = registry.by_capability(Capability.SEARCH)
        cheapest = registry.cheapest(required={Capability.REASONING})
    """

    def __init__(self) -> None:
        self._providers: dict[str, Provider] = {}

    def register(self, provider: Provider) -> None:
        """Register a provider. Key is '{name}/{model}'."""
        key = f"{provider.name}/{provider.model}"
        self._providers[key] = provider
        logger.info("Registered provider: %s", key)

    def unregister(self, key: str) -> None:
        """Remove a provider by key."""
        self._providers.pop(key, None)

    def get(self, key: str) -> Optional[Provider]:
        """Look up a provider by key (e.g. 'anthropic/claude-sonnet-4-6')."""
        return self._providers.get(key)

    def get_by_name(self, name: str) -> Optional[Provider]:
        """Find first provider matching a provider name (e.g. 'perplexity')."""
        for provider in self._providers.values():
            if provider.name == name:
                return provider
        return None

    def list_all(self) -> list[Provider]:
        """Return all registered providers."""
        return list(self._providers.values())

    def by_capability(self, capability: Capability) -> list[Provider]:
        """Return providers that support a given capability."""
        return [p for p in self._providers.values() if p.supports(capability)]

    def by_capabilities(self, required: set[Capability]) -> list[Provider]:
        """Return providers that support ALL given capabilities."""
        return [p for p in self._providers.values() if required.issubset(p.profile.capabilities)]

    def cheapest(self, required: Optional[set[Capability]] = None) -> Optional[Provider]:
        """Find the cheapest provider matching required capabilities.

        Cost is measured by (input + output) per 1k tokens.
        """
        candidates = self.by_capabilities(required) if required else self.list_all()
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda p: p.profile.cost_per_1k_input + p.profile.cost_per_1k_output,
        )

    def fastest(self, required: Optional[set[Capability]] = None) -> Optional[Provider]:
        """Find the lowest-latency provider matching required capabilities."""
        candidates = self.by_capabilities(required) if required else self.list_all()
        if not candidates:
            return None
        tier_order = {"low": 0, "medium": 1, "high": 2}
        return min(candidates, key=lambda p: tier_order.get(p.profile.latency_tier, 9))

    def profiles(self) -> list[ProviderProfile]:
        """Return profiles for all registered providers."""
        return [p.profile for p in self._providers.values()]

    def __len__(self) -> int:
        return len(self._providers)

    def __repr__(self) -> str:
        return f"ProviderRegistry({len(self)} providers)"


class ProviderRouter:
    """Selects the best provider for a task based on required capabilities.

    Strategy priority:
    1. Match all required capabilities
    2. Prefer cheaper providers (unless low_latency is required)
    3. Fallback to manual override if no match
    """

    def __init__(self, registry: ProviderRegistry) -> None:
        self._registry = registry

    def select(
        self,
        required: Optional[set[Capability]] = None,
        *,
        prefer: str = "cost",
        exclude: Optional[set[str]] = None,
    ) -> Optional[Provider]:
        """Select the best provider for given requirements.

        Args:
            required: Capabilities the provider must support.
            prefer: Selection strategy — 'cost' (cheapest) or 'speed' (lowest latency).
            exclude: Provider keys to exclude (e.g. after a failure for fallback).

        Returns:
            Best matching Provider, or None if no match.
        """
        required = required or set()
        exclude = exclude or set()

        candidates = self._registry.by_capabilities(required)
        candidates = [p for p in candidates if f"{p.name}/{p.model}" not in exclude]

        if not candidates:
            return None

        if prefer == "speed" or Capability.LOW_LATENCY in required:
            tier_order = {"low": 0, "medium": 1, "high": 2}
            candidates.sort(key=lambda p: tier_order.get(p.profile.latency_tier, 9))
        else:
            candidates.sort(key=lambda p: p.profile.cost_per_1k_input + p.profile.cost_per_1k_output)

        return candidates[0]

    def select_with_fallback(
        self,
        required: Optional[set[Capability]] = None,
        *,
        prefer: str = "cost",
        max_fallbacks: int = 3,
    ) -> list[Provider]:
        """Return a ranked list of providers for fallback chain.

        Args:
            required: Required capabilities.
            prefer: Selection strategy.
            max_fallbacks: Max providers to return.

        Returns:
            Ordered list of providers (best first).
        """
        required = required or set()
        candidates = self._registry.by_capabilities(required)

        if not candidates:
            return []

        if prefer == "speed" or Capability.LOW_LATENCY in required:
            tier_order = {"low": 0, "medium": 1, "high": 2}
            candidates.sort(key=lambda p: tier_order.get(p.profile.latency_tier, 9))
        else:
            candidates.sort(key=lambda p: p.profile.cost_per_1k_input + p.profile.cost_per_1k_output)

        return candidates[:max_fallbacks]
