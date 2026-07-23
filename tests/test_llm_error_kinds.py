"""LLMError carries a structured status/kind (used by failover + compaction)."""

from __future__ import annotations

import io
import urllib.error

import pytest

from birkin.llm import FAILOVER_KINDS, LLMClient, LLMError, _kind_for_status


def test_kind_for_status_table():
    assert _kind_for_status(401) == "auth"
    assert _kind_for_status(403) == "auth"
    assert _kind_for_status(402) == "billing"
    assert _kind_for_status(429) == "rate_limit"
    assert _kind_for_status(500) == "server"
    assert _kind_for_status(529) == "server"
    assert _kind_for_status(413) == "overflow"
    assert _kind_for_status(404) == "client"


def test_400_is_overflow_only_when_the_body_says_so():
    assert _kind_for_status(400, "prompt is too long: 250000 tokens") == "overflow"
    assert _kind_for_status(400, '{"error":{"message":"context window exceeded"}}') \
        == "overflow"
    assert _kind_for_status(400, "invalid tool schema") == "client"


def test_failover_kinds_exclude_deterministic_request_bugs():
    assert "client" not in FAILOVER_KINDS
    assert "overflow" not in FAILOVER_KINDS
    assert "timeout" not in FAILOVER_KINDS  # CLI subprocess stall
    assert {"auth", "billing", "rate_limit", "server", "network"} == set(FAILOVER_KINDS)


def _client() -> LLMClient:
    return LLMClient(provider="anthropic", model="m", api_key="k",
                     base_url="https://example.invalid")


def test_post_raises_with_status_and_kind(monkeypatch):
    def _raise(*a, **k):
        raise urllib.error.HTTPError(
            "u", 429, "Too Many Requests", {},
            io.BytesIO(b'{"error":"slow down"}'))

    monkeypatch.setattr("urllib.request.urlopen", _raise)
    monkeypatch.setattr("time.sleep", lambda *_: None)
    c = _client()
    with pytest.raises(LLMError) as exc:
        c._post("https://example.invalid", {}, {}, stream=False)
    assert exc.value.status == 429
    assert exc.value.kind == "rate_limit"


def test_post_overflow_400_is_not_retried_and_is_classified(monkeypatch):
    calls = {"n": 0}

    def _raise(*a, **k):
        calls["n"] += 1
        raise urllib.error.HTTPError(
            "u", 400, "Bad Request", {},
            io.BytesIO(b'{"error":{"message":"prompt is too long"}}'))

    monkeypatch.setattr("urllib.request.urlopen", _raise)
    monkeypatch.setattr("time.sleep", lambda *_: None)
    with pytest.raises(LLMError) as exc:
        _client()._post("https://example.invalid", {}, {}, stream=False)
    assert exc.value.kind == "overflow"
    assert calls["n"] == 1  # 400 is terminal — no backoff storm


def test_network_error_kind(monkeypatch):
    def _raise(*a, **k):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr("urllib.request.urlopen", _raise)
    monkeypatch.setattr("time.sleep", lambda *_: None)
    with pytest.raises(LLMError) as exc:
        _client()._post("https://example.invalid", {}, {}, stream=False)
    assert exc.value.kind == "network"
    assert exc.value.status is None


def test_bare_llmerror_still_constructs():
    # Existing raise sites pass only a message; defaults must stay harmless.
    err = LLMError("boom")
    assert err.status is None and err.kind == "unknown"
    assert err.kind not in FAILOVER_KINDS
