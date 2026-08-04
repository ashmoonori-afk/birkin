"""The pool has to be on the path build_client returns, or it protects nobody.

Every surface gets its client from llm.build_client, which already wraps for
provider failover. A credential pool belongs INSIDE that wrapper: spend the
other keys of the configured account first, and only then answer from a
different provider on a different model.
"""

from __future__ import annotations

from birkin import config, credpool, llm
from birkin.failover import FailoverClient

K1, K2 = "sk-ant-pool-one", "sk-ant-pool-two"


def test_multiple_keys_get_a_rotating_client() -> None:
    client = llm.build_client(
        {"provider": "anthropic", "model": "m", "api_keys": [K1, K2]}, K1)
    assert isinstance(client, credpool.RotatingClient)
    assert client.api_key == K1
    assert client.depth == 2


def test_one_key_stays_a_plain_client() -> None:
    """No list configured means nothing to rotate to -- stay out of the way."""
    client = llm.build_client({"provider": "anthropic", "model": "m"}, K1)
    assert isinstance(client, llm.LLMClient)


def test_the_rotation_sits_inside_the_failover_wrapper(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-the-fallback-key")
    client = llm.build_client(
        {"provider": "anthropic", "model": "m", "api_keys": [K1, K2],
         "fallback_provider": "openai", "fallback_model": "gpt-x"}, K1)
    assert isinstance(client, FailoverClient)
    assert isinstance(client.primary, credpool.RotatingClient)


def test_a_mid_session_setting_reaches_both_wrappers(monkeypatch) -> None:
    """FailoverClient.__setattr__ forwards to primary; primary is now a wrapper."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-the-fallback-key")
    client = llm.build_client(
        {"provider": "anthropic", "model": "m", "api_keys": [K1, K2],
         "fallback_provider": "openai", "fallback_model": "gpt-x"}, K1)
    client.temperature = 0.25
    assert client.primary.temperature == 0.25
    assert client.fallback.temperature == 0.25


def test_api_keys_is_a_documented_default() -> None:
    assert config.DEFAULT_CONFIG["api_keys"] == []
