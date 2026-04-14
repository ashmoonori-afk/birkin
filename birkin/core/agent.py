"""Agent class -- core conversation loop.

TODO(BRA-58): Expand with:
- Async conversation loop
- Streaming output
- Tool dispatch cycle (call -> result -> re-complete)
- Max-turn guardrails
"""

from __future__ import annotations

from birkin.core.providers.base import Message, Provider
from birkin.core.session import Session
from birkin.tools.base import Tool

_DEFAULT_SYSTEM_PROMPT = "You are Birkin, a helpful AI assistant."


class Agent:
    """Stateful agent wrapping a provider, tools, and a session."""

    def __init__(
        self,
        provider: Provider,
        *,
        tools: list[Tool] | None = None,
        session: Session | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self._provider = provider
        self._tools = tools or []
        self._session = session or Session()
        self._system_prompt = system_prompt or _DEFAULT_SYSTEM_PROMPT

    @property
    def session(self) -> Session:
        return self._session

    @property
    def provider(self) -> Provider:
        return self._provider

    def chat(self, user_input: str) -> str:
        """Send a user message and return the assistant's text reply.

        This is the synchronous, non-streaming path used by the CLI REPL.
        """
        self._session.append(Message(role="user", content=user_input))

        wire_messages = self._build_messages()
        tool_schemas = [t.to_provider_schema() for t in self._tools] or None

        response = self._provider.complete(wire_messages, tools=tool_schemas)
        self._session.append(response.message)
        return response.message.content

    def _build_messages(self) -> list[Message]:
        """Assemble the full message list including system prompt."""
        msgs: list[Message] = []
        if self._system_prompt:
            msgs.append(Message(role="system", content=self._system_prompt))
        msgs.extend(self._session.messages)
        return msgs
