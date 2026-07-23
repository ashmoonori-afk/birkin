"""Provider failover: switch on transient failures, return after cooldown."""

from __future__ import annotations

import pytest

from birkin import llm
from birkin.failover import FailoverClient
from birkin.llm import LLMError


class Stub:
    """Stands in for an LLMClient."""

    def __init__(self, provider="anthropic", model="m1", error=None):
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


def _pair(primary_error=None):
    primary = Stub("anthropic", "primary-model", primary_error)
    fallback = Stub("openai", "fallback-model")
    return primary, fallback, FailoverClient(primary, fallback, cooldown_s=300)


def _text(res):
    return res["content"][0]["text"]


# -- switching -------------------------------------------------------------

def test_healthy_primary_answers_and_fallback_is_untouched():
    primary, fallback, client = _pair()
    assert _text(client.complete(system="s", messages=[])) == "hi from primary-model"
    assert len(primary.calls) == 1 and not fallback.calls


@pytest.mark.parametrize("kind,status", [
    ("rate_limit", 429), ("server", 500), ("auth", 401),
    ("billing", 402), ("network", None),
])
def test_failover_kinds_switch_to_the_fallback(kind, status):
    primary, fallback, client = _pair(LLMError("down", status=status, kind=kind))
    assert _text(client.complete(system="s", messages=[])) == "hi from fallback-model"
    assert client.on_fallback is True


@pytest.mark.parametrize("kind,status", [
    ("client", 400), ("overflow", 413), ("timeout", None), ("unknown", None),
])
def test_non_failover_kinds_propagate(kind, status):
    primary, fallback, client = _pair(LLMError("nope", status=status, kind=kind))
    with pytest.raises(LLMError):
        client.complete(system="s", messages=[])
    assert not fallback.calls
    assert client.on_fallback is False


def test_fallback_answers_as_itself_not_as_the_primary_model():
    # Agent passes model=cfg["model"] — the PRIMARY's id. Handing that to a
    # different provider would 404.
    primary, fallback, client = _pair(LLMError("x", status=429, kind="rate_limit"))
    client.complete(system="s", messages=[], model="primary-model")
    assert fallback.calls[0]["model"] == "fallback-model"


# -- cooldown --------------------------------------------------------------

def test_cooldown_parks_on_the_fallback_without_retrying_the_primary():
    primary, fallback, client = _pair(LLMError("x", status=429, kind="rate_limit"))
    client.complete(system="s", messages=[])
    before = len(primary.calls)
    client.complete(system="s", messages=[])
    client.complete(system="s", messages=[])
    assert len(primary.calls) == before          # not re-probed during cooldown
    assert len(fallback.calls) == 3


def test_primary_is_retried_and_resumes_after_the_cooldown(monkeypatch):
    now = {"t": 1000.0}
    monkeypatch.setattr("birkin.failover.time.monotonic", lambda: now["t"])

    primary, fallback, client = _pair(LLMError("x", status=429, kind="rate_limit"))
    client.complete(system="s", messages=[])
    assert client.on_fallback is True

    now["t"] += 301                              # cooldown elapsed
    assert client.on_fallback is False
    primary.error = None                         # provider recovered
    assert _text(client.complete(system="s", messages=[])) == "hi from primary-model"
    assert client._down_until == 0.0


def test_still_failing_primary_after_cooldown_rearms(monkeypatch):
    now = {"t": 1000.0}
    monkeypatch.setattr("birkin.failover.time.monotonic", lambda: now["t"])

    primary, fallback, client = _pair(LLMError("x", status=500, kind="server"))
    client.complete(system="s", messages=[])
    now["t"] += 301
    client.complete(system="s", messages=[])
    assert client.on_fallback is True


def test_fallback_failure_surfaces():
    primary, fallback, client = _pair(LLMError("x", status=429, kind="rate_limit"))
    fallback.error = LLMError("fallback dead", status=500, kind="server")
    with pytest.raises(LLMError, match="fallback dead"):
        client.complete(system="s", messages=[])


# -- transparency ----------------------------------------------------------

def test_attribute_writes_reach_both_clients():
    primary, fallback, client = _pair()
    client.temperature = 0.2
    client.cli_access = "full"
    said: list[str] = []
    client._status = said.append
    for c in (primary, fallback):
        assert c.temperature == 0.2
        assert c.cli_access == "full"
        c._status("ping")                    # both sinks reach the same list
    assert said == ["ping", "ping"]


def test_reads_report_the_active_client():
    primary, fallback, client = _pair(LLMError("x", status=429, kind="rate_limit"))
    assert client.provider == "anthropic" and client.model == "primary-model"
    client.complete(system="s", messages=[])
    assert client.provider == "openai" and client.model == "fallback-model"


def test_switch_is_announced_through_the_status_sink():
    primary, fallback, client = _pair(LLMError("x", status=429, kind="rate_limit"))
    said: list[str] = []
    client._status = said.append
    client.complete(system="s", messages=[])
    assert said and "openai/fallback-model" in said[0] and "rate_limit" in said[0]


# -- build_client wiring ---------------------------------------------------

def _cfg(**kw):
    base = {"provider": "anthropic", "model": "claude-sonnet-4-6",
            "api_key": "sk-test", "base_url": ""}
    base.update(kw)
    return base


def test_no_fallback_configured_returns_a_plain_client():
    client = llm.build_client(_cfg(), "sk-test")
    assert isinstance(client, llm.LLMClient)


def test_fallback_configured_returns_a_wrapper(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-oai")
    client = llm.build_client(
        _cfg(fallback_provider="openai", fallback_model="gpt-4o"), "sk-test")
    assert isinstance(client, FailoverClient)
    assert client.primary.model == "claude-sonnet-4-6"
    assert client.fallback.provider == "openai"
    assert client.fallback.model == "gpt-4o"


def test_fallback_without_credentials_degrades_to_plain(monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = _cfg(fallback_provider="openai", fallback_model="gpt-4o")
    cfg["api_key"] = None
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    client = llm.build_client(cfg, "sk-test")
    assert isinstance(client, llm.LLMClient)
    assert "no credentials" in capsys.readouterr().out


def test_cli_primary_is_never_wrapped(monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-oai")
    client = llm.build_client(
        _cfg(provider="claude-cli", fallback_provider="openai",
             fallback_model="gpt-4o"), "cli")
    assert isinstance(client, llm.LLMClient)
    assert "ignored for provider" in capsys.readouterr().out


def test_fallback_identical_to_primary_is_not_wrapped():
    client = llm.build_client(
        _cfg(fallback_provider="anthropic", fallback_model="claude-sonnet-4-6"),
        "sk-test")
    assert isinstance(client, llm.LLMClient)
