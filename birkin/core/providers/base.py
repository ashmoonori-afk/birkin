"""Abstract provider interface and shared data types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Message:
    """A single message in a conversation."""

    role: str  # "system" | "user" | "assistant" | "tool"
    content: str
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None


@dataclass(frozen=True)
class ProviderResponse:
    """Response returned by a provider after completion."""

    message: Message
    usage: dict[str, int] = field(default_factory=dict)
    stop_reason: str | None = None


class Provider(ABC):
    """Abstract base class for LLM providers.

    Concrete implementations (OpenAI, Anthropic) must implement both
    sync and async completion methods.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g. 'openai', 'anthropic')."""
        ...

    @property
    @abstractmethod
    def model(self) -> str:
        """Active model name."""
        ...

    @abstractmethod
    def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> ProviderResponse:
        """Synchronous completion."""
        ...

    @abstractmethod
    async def acomplete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> ProviderResponse:
        """Asynchronous completion."""
        ...
