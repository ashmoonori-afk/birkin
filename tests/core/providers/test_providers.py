"""Tests for provider interfaces and factory."""

import pytest

from birkin.core.providers import create_provider
from birkin.core.providers.base import Message, Provider, ProviderResponse
from birkin.core.providers.anthropic import AnthropicProvider
from birkin.core.providers.openai import OpenAIProvider


class TestMessage:
    def test_is_frozen(self):
        msg = Message(role="user", content="hello")
        with pytest.raises(AttributeError):
            msg.role = "assistant"  # type: ignore[misc]

    def test_defaults(self):
        msg = Message(role="user", content="hello")
        assert msg.tool_calls is None
        assert msg.tool_call_id is None


class TestProviderResponse:
    def test_defaults(self):
        msg = Message(role="assistant", content="hi")
        resp = ProviderResponse(message=msg)
        assert resp.usage == {}
        assert resp.stop_reason is None


class TestCreateProvider:
    def test_creates_openai(self):
        p = create_provider("openai")
        assert isinstance(p, OpenAIProvider)
        assert p.name == "openai"

    def test_creates_anthropic(self):
        p = create_provider("anthropic")
        assert isinstance(p, AnthropicProvider)
        assert p.name == "anthropic"

    def test_model_override(self):
        p = create_provider("openai", model="gpt-4o-mini")
        assert p.model == "gpt-4o-mini"

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            create_provider("gemini")


class TestProviderStubs:
    def test_openai_complete_not_implemented(self):
        p = OpenAIProvider()
        with pytest.raises(NotImplementedError):
            p.complete([Message(role="user", content="hi")])

    def test_anthropic_complete_not_implemented(self):
        p = AnthropicProvider()
        with pytest.raises(NotImplementedError):
            p.complete([Message(role="user", content="hi")])

    @pytest.mark.asyncio
    async def test_openai_acomplete_not_implemented(self):
        p = OpenAIProvider()
        with pytest.raises(NotImplementedError):
            await p.acomplete([Message(role="user", content="hi")])

    @pytest.mark.asyncio
    async def test_anthropic_acomplete_not_implemented(self):
        p = AnthropicProvider()
        with pytest.raises(NotImplementedError):
            await p.acomplete([Message(role="user", content="hi")])
