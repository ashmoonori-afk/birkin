"""Tests for Agent class."""

from __future__ import annotations

from typing import Any

from birkin.core.agent import Agent
from birkin.core.providers.base import Message, Provider, ProviderResponse
from birkin.core.session import Session


class FakeProvider(Provider):
    """In-memory provider for testing."""

    def __init__(self, reply: str = "fake reply") -> None:
        self._reply = reply
        self.last_messages: list[Message] = []

    @property
    def name(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return "fake-v1"

    def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> ProviderResponse:
        self.last_messages = messages
        return ProviderResponse(
            message=Message(role="assistant", content=self._reply),
        )

    async def acomplete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> ProviderResponse:
        return self.complete(messages, tools=tools)


class TestAgent:
    def test_chat_returns_provider_reply(self):
        provider = FakeProvider(reply="hello back")
        agent = Agent(provider=provider)
        result = agent.chat("hi")
        assert result == "hello back"

    def test_chat_appends_to_session(self):
        provider = FakeProvider()
        agent = Agent(provider=provider)
        agent.chat("first")
        assert agent.session.message_count == 2  # user + assistant

    def test_system_prompt_prepended(self):
        provider = FakeProvider()
        agent = Agent(provider=provider, system_prompt="Be brief.")
        agent.chat("test")
        assert provider.last_messages[0].role == "system"
        assert provider.last_messages[0].content == "Be brief."

    def test_uses_provided_session(self):
        session = Session()
        session.append(Message(role="user", content="earlier"))
        provider = FakeProvider()
        agent = Agent(provider=provider, session=session)
        agent.chat("now")
        # 1 pre-existing + 1 new user + 1 new assistant = 3
        assert agent.session.message_count == 3

    def test_default_system_prompt(self):
        provider = FakeProvider()
        agent = Agent(provider=provider)
        agent.chat("test")
        assert "Birkin" in provider.last_messages[0].content
