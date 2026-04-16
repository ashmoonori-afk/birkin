"""Tests for provider interfaces and factory."""

import pytest

from birkin.core.models import Message
from birkin.core.providers import create_provider
from birkin.core.providers.anthropic import AnthropicProvider
from birkin.core.providers.base import (
    ModelCapabilities,
    ProviderResponse,
    TokenUsage,
)
from birkin.core.providers.openai import OpenAIProvider


class TestMessage:
    def test_defaults(self):
        msg = Message(role="user", content="hello")
        assert msg.tool_calls is None
        assert msg.tool_call_id is None


class TestProviderResponse:
    def test_defaults(self):
        resp = ProviderResponse(content="hi", tool_calls=None, stop_reason="end_turn")
        assert resp.content == "hi"
        assert resp.tool_calls is None
        assert resp.stop_reason == "end_turn"

    def test_with_usage(self):
        usage = TokenUsage(prompt_tokens=10, completion_tokens=5)
        resp = ProviderResponse(content="ok", tool_calls=None, stop_reason="end_turn", usage=usage)
        assert resp.usage.prompt_tokens == 10
        assert resp.usage.completion_tokens == 5
        assert resp.usage.total_tokens == 15


class TestModelCapabilities:
    def test_context_window(self):
        caps = ModelCapabilities(context_window=200000)
        assert caps.context_window == 200000


class TestCreateProvider:
    def test_creates_openai(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        p = create_provider("openai/gpt-4o")
        assert isinstance(p, OpenAIProvider)
        assert p.name == "openai"
        assert p.model == "gpt-4o"

    def test_creates_anthropic(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        p = create_provider("anthropic/claude-sonnet-4-6")
        assert isinstance(p, AnthropicProvider)
        assert p.name == "anthropic"
        assert p.model == "claude-sonnet-4-6"

    def test_bare_model_defaults_to_openai(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        p = create_provider("gpt-4o-mini")
        assert isinstance(p, OpenAIProvider)
        assert p.model == "gpt-4o-mini"

    def test_default_model(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        p = create_provider("anthropic/default")
        assert isinstance(p, AnthropicProvider)
        assert p.model == "claude-sonnet-4-6"

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            create_provider("gemini/model")

    def test_openrouter(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        p = create_provider("openrouter/meta-llama/llama-3-70b")
        assert isinstance(p, OpenAIProvider)


class TestProviderInstantiation:
    def test_anthropic_with_key(self):
        p = AnthropicProvider(model="claude-sonnet-4-6", api_key="test-key")
        assert p.name == "anthropic"
        assert p.model == "claude-sonnet-4-6"

    def test_openai_with_key(self):
        p = OpenAIProvider(model="gpt-4o", api_key="test-key")
        assert p.name == "openai"
        assert p.model == "gpt-4o"

    def test_anthropic_default_model(self):
        p = AnthropicProvider(api_key="test-key")
        assert p.model == "claude-sonnet-4-6"

    def test_openai_default_model(self):
        p = OpenAIProvider(api_key="test-key")
        assert p.model == "gpt-4o"

    def test_anthropic_capabilities(self):
        p = AnthropicProvider(api_key="test-key")
        caps = p.capabilities()
        assert caps.context_window > 0

    def test_openai_capabilities(self):
        p = OpenAIProvider(api_key="test-key")
        caps = p.capabilities()
        assert caps.context_window > 0

    @pytest.mark.parametrize(
        "model_id",
        [
            "claude-opus-4-6",
            "claude-sonnet-4-6",
            "claude-haiku-4-5-20251001",
        ],
    )
    def test_anthropic_model_capabilities(self, model_id: str):
        p = AnthropicProvider(model=model_id, api_key="test-key")
        caps = p.capabilities()
        assert isinstance(caps, ModelCapabilities)
        assert caps.context_window == 200000
