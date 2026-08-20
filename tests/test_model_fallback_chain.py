"""An ordered fallback chain across N models, and the three new providers.

Before this, ``_maybe_wrap_failover`` understood exactly one fallback
(``fallback_provider`` / ``fallback_model``), so a rate-limited primary had a
single place to go and a rate-limited pair had nowhere. The chain is built by
right-folding the existing two-client :class:`FailoverClient`, so each hop keeps
its own cooldown and the wrapper itself is unchanged.
"""

from __future__ import annotations

import pytest

from birkin import config, llm
from birkin.llm import LLMError


class Stub:
    """Stands in for an LLMClient (same shape as tests/test_failover.py)."""

    def __init__(self, provider: str, model: str, error: Exception | None = None):
        self.provider = provider
        self.model = model
        self.error = error
        self.calls: list[dict] = []
        self._status = None
        self.temperature = 1.0
        self.cli_access = "workspace"

    def complete(self, **kw):
        self.calls.append(kw)
        if self.error is not None:
            raise self.error
        return {"role": "assistant",
                "content": [{"type": "text", "text": f"hi from {self.model}"}],
                "stop_reason": "end_turn"}


def _rate_limited() -> LLMError:
    return LLMError("busy", status=429, kind="rate_limit")


@pytest.fixture()
def wire(monkeypatch):
    """Build clients from cfg without touching the network, and always find a key."""
    built: dict[str, Stub] = {}
    errors: dict[str, Exception] = {}

    def fake_plain_client(cfg, api_key):
        provider = cfg.get("provider", "")
        model = cfg.get("model", "")
        stub = Stub(provider, model, errors.get(provider))
        built[provider] = stub
        return stub

    monkeypatch.setattr(llm, "_plain_client", fake_plain_client)
    monkeypatch.setattr(config, "get_api_key", lambda cfg: "test-key")
    return built, errors


# -- item 8: the ordered chain --------------------------------------------

def test_chain_falls_through_two_dead_models_to_the_third(wire):
    built, errors = wire
    errors["anthropic"] = _rate_limited()
    errors["gemini"] = _rate_limited()
    cfg = {
        "provider": "anthropic", "model": "primary",
        "fallback_chain": [
            {"provider": "gemini", "model": "gemini-3.7-flash"},
            {"provider": "nvidia", "model": "meta/llama-3.1-8b-instruct"},
        ],
    }
    primary = llm._plain_client(cfg, "test-key")
    client = llm._maybe_wrap_failover(cfg, primary)
    reply = client.complete(system="s", messages=[])
    assert reply["content"][0]["text"] == "hi from meta/llama-3.1-8b-instruct"


def test_chain_prefers_the_primary_while_it_is_healthy(wire):
    built, errors = wire
    cfg = {
        "provider": "anthropic", "model": "primary",
        "fallback_chain": [{"provider": "gemini", "model": "gemini-3.7-flash"}],
    }
    primary = llm._plain_client(cfg, "test-key")
    client = llm._maybe_wrap_failover(cfg, primary)
    assert client.complete(system="s", messages=[])["content"][0]["text"] == "hi from primary"
    assert not built["gemini"].calls


def test_the_legacy_single_fallback_still_works(wire):
    """fallback_provider/fallback_model must keep behaving exactly as before."""
    built, errors = wire
    errors["anthropic"] = _rate_limited()
    cfg = {"provider": "anthropic", "model": "primary",
           "fallback_provider": "openai", "fallback_model": "gpt-4.1-mini"}
    primary = llm._plain_client(cfg, "test-key")
    client = llm._maybe_wrap_failover(cfg, primary)
    assert client.complete(system="s", messages=[])["content"][0]["text"] == "hi from gpt-4.1-mini"


def test_the_legacy_fallback_runs_before_the_chain(wire):
    built, errors = wire
    errors["anthropic"] = _rate_limited()
    cfg = {"provider": "anthropic", "model": "primary",
           "fallback_provider": "openai", "fallback_model": "gpt-4.1-mini",
           "fallback_chain": [{"provider": "gemini", "model": "gemini-3.7-flash"}]}
    primary = llm._plain_client(cfg, "test-key")
    client = llm._maybe_wrap_failover(cfg, primary)
    assert client.complete(system="s", messages=[])["content"][0]["text"] == "hi from gpt-4.1-mini"
    assert "gemini" not in built or not built["gemini"].calls


# -- item 8, edge cases (criterion C2) ------------------------------------

@pytest.mark.parametrize("entry", [
    {},
    {"provider": "gemini"},
    {"model": "gemini-3.7-flash"},
    {"provider": "", "model": ""},
    "not-a-dict",
    None,
])
def test_malformed_chain_entries_are_skipped_not_fatal(wire, entry):
    built, errors = wire
    cfg = {"provider": "anthropic", "model": "primary", "fallback_chain": [entry]}
    primary = llm._plain_client(cfg, "test-key")
    client = llm._maybe_wrap_failover(cfg, primary)
    # No usable fallback: degrade to today's behavior, never crash.
    assert client is primary


def test_a_chain_entry_without_credentials_is_skipped(monkeypatch, wire):
    built, errors = wire
    monkeypatch.setattr(config, "get_api_key",
                        lambda cfg: None if cfg.get("provider") == "gemini" else "k")
    errors["anthropic"] = _rate_limited()
    cfg = {"provider": "anthropic", "model": "primary",
           "fallback_chain": [
               {"provider": "gemini", "model": "gemini-3.7-flash"},
               {"provider": "nvidia", "model": "meta/llama-3.1-8b-instruct"},
           ]}
    primary = llm._plain_client(cfg, "test-key")
    client = llm._maybe_wrap_failover(cfg, primary)
    reply = client.complete(system="s", messages=[])
    assert reply["content"][0]["text"] == "hi from meta/llama-3.1-8b-instruct"


def test_an_entry_identical_to_the_primary_is_skipped(wire):
    built, errors = wire
    cfg = {"provider": "anthropic", "model": "primary",
           "fallback_chain": [{"provider": "anthropic", "model": "primary"}]}
    primary = llm._plain_client(cfg, "test-key")
    assert llm._maybe_wrap_failover(cfg, primary) is primary


def test_an_exhausted_chain_raises_the_last_error_not_none(wire):
    built, errors = wire
    errors["anthropic"] = _rate_limited()
    errors["gemini"] = _rate_limited()
    cfg = {"provider": "anthropic", "model": "primary",
           "fallback_chain": [{"provider": "gemini", "model": "gemini-3.7-flash"}]}
    primary = llm._plain_client(cfg, "test-key")
    client = llm._maybe_wrap_failover(cfg, primary)
    with pytest.raises(LLMError):
        client.complete(system="s", messages=[])


# -- item 7: the three new providers (criterion C3) ------------------------

@pytest.mark.parametrize(("provider", "env", "host"), [
    ("gemini", "GEMINI_API_KEY", "generativelanguage.googleapis.com"),
    ("nvidia", "NVIDIA_API_KEY", "integrate.api.nvidia.com"),
    ("freellmapi", "FREELLMAPI_API_KEY", "localhost:3001"),
])
def test_new_providers_are_registered_openai_compatible(provider, env, host):
    assert llm._transport_for(provider) == "openai_chat", (
        f"{provider} has no wire transport, so complete() would raise"
    )
    assert config.PROVIDER_API_KEY_ENV[provider] == env
    assert host in config.PROVIDER_DEFAULT_BASE_URL[provider]


@pytest.mark.parametrize("provider", ["gemini", "nvidia", "freellmapi"])
def test_a_new_provider_without_a_key_resolves_to_none_not_an_exception(
    monkeypatch, provider,
):
    for env in ("GEMINI_API_KEY", "NVIDIA_API_KEY", "FREELLMAPI_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    assert config.get_api_key({"provider": provider}) is None


def test_an_unknown_provider_still_has_no_transport():
    assert llm._transport_for("definitely-not-a-provider") == ""


def test_base_url_resolution_prefers_explicit_config(monkeypatch):
    assert config.resolve_base_url({"provider": "nvidia"}) == \
        config.PROVIDER_DEFAULT_BASE_URL["nvidia"].rstrip("/")
    assert config.resolve_base_url(
        {"provider": "nvidia", "base_url": "http://127.0.0.1:9/v1/"}
    ) == "http://127.0.0.1:9/v1"


# -- item 7: the new providers through the curation registry --------------
# birkin/providers.py is the *curation* registry (a model is a pure text
# generator there). Registering a provider in the LLM layer does not make it
# reachable from curation, so the three new providers are wired here too.

@pytest.mark.parametrize("provider", ["gemini-api", "nvidia", "freellmapi"])
def test_new_providers_resolve_through_the_curation_registry(
    monkeypatch, provider,
):
    from birkin import providers

    for env in ("GEMINI_API_KEY", "NVIDIA_API_KEY", "FREELLMAPI_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    complete = providers.get_completer(provider, cfg={})
    reply = complete("say hi")
    # No credentials must degrade to the in-band typed error the curation
    # executor understands, never an exception.
    assert reply.startswith("[provider-error]"), reply
    assert provider.split("-")[0] in reply


def test_the_cli_gemini_provider_still_means_the_cli():
    """`gemini` stayed the CLI wrapper; the HTTP API is `gemini-api`."""
    from birkin import providers

    assert providers.get_completer("gemini") is not None


def test_an_unknown_curation_provider_still_raises():
    from birkin import providers

    with pytest.raises(ValueError, match="unknown curation provider"):
        providers.get_completer("definitely-not-a-provider")
