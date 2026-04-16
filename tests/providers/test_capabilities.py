"""Tests for provider capabilities, profiles, registry, and router."""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock

import pytest

from birkin.core.providers.base import Provider
from birkin.core.providers.capabilities import Capability, ProviderProfile
from birkin.core.providers.registry import ProviderRegistry, ProviderRouter

# ---------------------------------------------------------------------------
# Fixtures — mock providers with controlled profiles
# ---------------------------------------------------------------------------


def _make_provider(
    name: str,
    model: str,
    capabilities: set[Capability],
    cost_in: float = 1.0,
    cost_out: float = 5.0,
    latency: str = "medium",
    local: bool = False,
) -> Provider:
    """Create a mock Provider with a specific profile."""
    profile = ProviderProfile(
        name=name,
        model=model,
        capabilities=frozenset(capabilities),
        cost_per_1k_input=cost_in,
        cost_per_1k_output=cost_out,
        max_context=128000,
        latency_tier=latency,
        local=local,
    )
    mock = MagicMock(spec=Provider)
    mock.name = name
    mock.model = model
    type(mock).profile = PropertyMock(return_value=profile)
    mock.supports = lambda cap: profile.supports(cap)
    return mock


# ---------------------------------------------------------------------------
# Capability + ProviderProfile tests
# ---------------------------------------------------------------------------


class TestCapability:
    def test_enum_values(self) -> None:
        assert Capability.REASONING == "reasoning"
        assert Capability.SEARCH == "search"
        assert Capability.LOW_LATENCY == "low_latency"

    def test_membership(self) -> None:
        caps = frozenset({Capability.REASONING, Capability.CODE})
        assert Capability.REASONING in caps
        assert Capability.SEARCH not in caps


class TestProviderProfile:
    def test_basic_creation(self) -> None:
        p = ProviderProfile(name="test", model="test-v1")
        assert p.name == "test"
        assert p.capabilities == frozenset()
        assert p.cost_per_1k_input == 0.0
        assert p.local is False

    def test_supports(self) -> None:
        p = ProviderProfile(
            name="x",
            model="x-1",
            capabilities=frozenset({Capability.REASONING, Capability.SEARCH}),
        )
        assert p.supports(Capability.REASONING) is True
        assert p.supports(Capability.SEARCH) is True
        assert p.supports(Capability.VISION) is False

    def test_frozen(self) -> None:
        p = ProviderProfile(name="x", model="x-1")
        with pytest.raises(Exception):
            p.name = "changed"


# ---------------------------------------------------------------------------
# Existing provider profile tests
# ---------------------------------------------------------------------------


class TestExistingProviderProfiles:
    def test_anthropic_profile(self) -> None:
        from birkin.core.providers.anthropic import AnthropicProvider

        try:
            p = AnthropicProvider(api_key="test-key")
        except Exception:
            pytest.skip("Cannot instantiate AnthropicProvider")
        profile = p.profile
        assert profile.name == "anthropic"
        assert Capability.REASONING in profile.capabilities
        assert Capability.TOOL_USE in profile.capabilities
        assert profile.max_context == 200000

    def test_openai_profile(self) -> None:
        from birkin.core.providers.openai import OpenAIProvider

        try:
            p = OpenAIProvider(api_key="test-key")
        except Exception:
            pytest.skip("Cannot instantiate OpenAIProvider")
        profile = p.profile
        assert profile.name == "openai"
        assert Capability.REASONING in profile.capabilities
        assert Capability.VISION in profile.capabilities

    def test_ollama_profile(self) -> None:
        from birkin.core.providers.ollama import OllamaProvider

        p = OllamaProvider(model="llama3.1")
        profile = p.profile
        assert profile.name == "ollama"
        assert profile.local is True
        assert profile.cost_per_1k_input == 0.0
        assert Capability.REASONING in profile.capabilities

    def test_provider_base_default_profile(self) -> None:
        """Test that Provider.profile default implementation works."""
        from birkin.core.providers.openai import OpenAIProvider

        try:
            p = OpenAIProvider(api_key="test-key")
        except Exception:
            pytest.skip("Cannot instantiate OpenAIProvider")
        assert p.supports(Capability.REASONING) is True


# ---------------------------------------------------------------------------
# New provider profile tests
# ---------------------------------------------------------------------------


class TestNewProviderProfiles:
    def test_perplexity_profile(self) -> None:
        from birkin.core.providers.perplexity import PerplexityProvider

        try:
            p = PerplexityProvider(api_key="test-key")
        except Exception:
            pytest.skip("Cannot instantiate PerplexityProvider")
        profile = p.profile
        assert profile.name == "perplexity"
        assert Capability.SEARCH in profile.capabilities
        assert Capability.REASONING in profile.capabilities

    def test_gemini_profile(self) -> None:
        from birkin.core.providers.gemini import GeminiProvider

        try:
            p = GeminiProvider(api_key="test-key")
        except Exception:
            pytest.skip("Cannot instantiate GeminiProvider")
        profile = p.profile
        assert profile.name == "gemini"
        assert Capability.VISION in profile.capabilities
        assert Capability.LONG_CONTEXT in profile.capabilities
        assert profile.max_context == 1000000

    def test_groq_profile(self) -> None:
        from birkin.core.providers.groq import GroqProvider

        try:
            p = GroqProvider(api_key="test-key")
        except Exception:
            pytest.skip("Cannot instantiate GroqProvider")
        profile = p.profile
        assert profile.name == "groq"
        assert Capability.LOW_LATENCY in profile.capabilities
        assert profile.latency_tier == "low"


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------


class TestProviderRegistry:
    def test_register_and_list(self) -> None:
        reg = ProviderRegistry()
        p1 = _make_provider("a", "m1", {Capability.REASONING})
        p2 = _make_provider("b", "m2", {Capability.SEARCH})
        reg.register(p1)
        reg.register(p2)
        assert len(reg) == 2

    def test_get_by_key(self) -> None:
        reg = ProviderRegistry()
        p = _make_provider("anthropic", "claude", {Capability.REASONING})
        reg.register(p)
        assert reg.get("anthropic/claude") is p
        assert reg.get("nonexistent/x") is None

    def test_get_by_name(self) -> None:
        reg = ProviderRegistry()
        p = _make_provider("perplexity", "sonar", {Capability.SEARCH})
        reg.register(p)
        assert reg.get_by_name("perplexity") is p
        assert reg.get_by_name("nonexistent") is None

    def test_by_capability(self) -> None:
        reg = ProviderRegistry()
        reg.register(_make_provider("a", "m1", {Capability.REASONING, Capability.SEARCH}))
        reg.register(_make_provider("b", "m2", {Capability.REASONING}))
        reg.register(_make_provider("c", "m3", {Capability.CODE}))

        reasoning = reg.by_capability(Capability.REASONING)
        assert len(reasoning) == 2

        search = reg.by_capability(Capability.SEARCH)
        assert len(search) == 1

    def test_by_capabilities_multiple(self) -> None:
        reg = ProviderRegistry()
        reg.register(_make_provider("a", "m1", {Capability.REASONING, Capability.CODE}))
        reg.register(_make_provider("b", "m2", {Capability.REASONING}))

        both = reg.by_capabilities({Capability.REASONING, Capability.CODE})
        assert len(both) == 1
        assert both[0].name == "a"

    def test_cheapest(self) -> None:
        reg = ProviderRegistry()
        reg.register(_make_provider("expensive", "m1", {Capability.REASONING}, cost_in=10.0, cost_out=30.0))
        reg.register(_make_provider("cheap", "m2", {Capability.REASONING}, cost_in=0.1, cost_out=0.5))

        assert reg.cheapest({Capability.REASONING}).name == "cheap"

    def test_fastest(self) -> None:
        reg = ProviderRegistry()
        reg.register(_make_provider("slow", "m1", {Capability.REASONING}, latency="high"))
        reg.register(_make_provider("fast", "m2", {Capability.REASONING}, latency="low"))

        assert reg.fastest({Capability.REASONING}).name == "fast"

    def test_cheapest_no_match(self) -> None:
        reg = ProviderRegistry()
        reg.register(_make_provider("a", "m1", {Capability.CODE}))
        assert reg.cheapest({Capability.SEARCH}) is None


# ---------------------------------------------------------------------------
# Router tests
# ---------------------------------------------------------------------------


class TestProviderRouter:
    def _build_registry(self) -> ProviderRegistry:
        reg = ProviderRegistry()
        reg.register(
            _make_provider(
                "anthropic",
                "claude",
                {Capability.REASONING, Capability.CODE, Capability.TOOL_USE},
                cost_in=3.0,
                cost_out=15.0,
                latency="medium",
            )
        )
        reg.register(
            _make_provider(
                "groq",
                "llama",
                {Capability.REASONING, Capability.CODE, Capability.LOW_LATENCY},
                cost_in=0.5,
                cost_out=0.8,
                latency="low",
            )
        )
        reg.register(
            _make_provider(
                "perplexity",
                "sonar",
                {Capability.SEARCH, Capability.REASONING},
                cost_in=1.0,
                cost_out=5.0,
                latency="medium",
            )
        )
        reg.register(
            _make_provider(
                "ollama",
                "llama-local",
                {Capability.REASONING, Capability.CODE},
                cost_in=0.0,
                cost_out=0.0,
                latency="high",
                local=True,
            )
        )
        return reg

    def test_select_by_cost(self) -> None:
        router = ProviderRouter(self._build_registry())
        best = router.select(required={Capability.REASONING}, prefer="cost")
        assert best.name == "ollama"  # cheapest (free)

    def test_select_by_speed(self) -> None:
        router = ProviderRouter(self._build_registry())
        best = router.select(required={Capability.REASONING}, prefer="speed")
        assert best.name == "groq"  # lowest latency

    def test_select_search(self) -> None:
        router = ProviderRouter(self._build_registry())
        best = router.select(required={Capability.SEARCH})
        assert best.name == "perplexity"

    def test_select_no_match(self) -> None:
        router = ProviderRouter(self._build_registry())
        assert router.select(required={Capability.AUDIO}) is None

    def test_select_with_exclude(self) -> None:
        router = ProviderRouter(self._build_registry())
        best = router.select(
            required={Capability.REASONING},
            prefer="cost",
            exclude={"ollama/llama-local"},
        )
        assert best.name == "groq"  # next cheapest after ollama excluded

    def test_fallback_chain(self) -> None:
        router = ProviderRouter(self._build_registry())
        chain = router.select_with_fallback(required={Capability.CODE}, max_fallbacks=3)
        assert len(chain) == 3
        # Ordered by cost: ollama (0) → groq (1.3) → anthropic (18)
        assert chain[0].name == "ollama"

    def test_fallback_chain_speed(self) -> None:
        router = ProviderRouter(self._build_registry())
        chain = router.select_with_fallback(required={Capability.REASONING}, prefer="speed")
        assert chain[0].name == "groq"  # fastest

    def test_low_latency_capability_forces_speed(self) -> None:
        router = ProviderRouter(self._build_registry())
        best = router.select(required={Capability.LOW_LATENCY}, prefer="cost")
        # LOW_LATENCY in required forces speed-based selection
        assert best.name == "groq"


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------


class TestCreateProvider:
    def test_factory_ollama(self) -> None:
        from birkin.core.providers import create_provider

        p = create_provider("ollama/llama3.1")
        assert p.name == "ollama"
        assert p.model == "llama3.1"

    def test_factory_unknown_raises(self) -> None:
        from birkin.core.providers import create_provider

        with pytest.raises(ValueError, match="Unknown provider"):
            create_provider("unknown/model")

    def test_factory_error_message_includes_new_providers(self) -> None:
        from birkin.core.providers import create_provider

        with pytest.raises(ValueError, match="perplexity"):
            create_provider("unknown/model")
