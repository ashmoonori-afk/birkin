"""Abstract provider interface and shared data types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from birkin.core.models import Message, ToolCall


@dataclass(frozen=True)
class TokenUsage:
    """Token usage statistics from a provider."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int = 0

    def __post_init__(self) -> None:
        if self.total_tokens == 0:
            object.__setattr__(
                self, "total_tokens", self.prompt_tokens + self.completion_tokens
            )


@dataclass(frozen=True)
class ModelCapabilities:
    """Capabilities of a specific LLM model."""

    context_window: int
    supports_tools: bool = True
    supports_vision: bool = False
    supports_streaming: bool = True


@dataclass(frozen=True)
class ProviderResponse:
    """Response returned by a provider after completion."""

    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    usage: TokenUsage | None = None
    stop_reason: str | None = None
    model: str | None = None


class ProviderErrorKind(Enum):
    """Classification of provider errors for retry/backoff logic."""

    RATE_LIMIT = "rate_limit"
    AUTH = "auth"
    CONTEXT_OVERFLOW = "context_overflow"
    SERVER = "server"
    NETWORK = "network"
    UNKNOWN = "unknown"


class ProviderError(Exception):
    """Exception raised by provider operations."""

    def __init__(
        self,
        message: str,
        kind: ProviderErrorKind = ProviderErrorKind.UNKNOWN,
        original_error: Exception | None = None,
    ) -> None:
        self.message = message
        self.kind = kind
        self.original_error = original_error
        super().__init__(message)


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
    def capabilities(self) -> ModelCapabilities:
        """Return the capabilities of the active model."""
        ...

    def supports_tools(self) -> bool:
        """Check if the active model supports tool use."""
        return self.capabilities().supports_tools

    def supports_streaming(self) -> bool:
        """Check if the active model supports streaming."""
        return self.capabilities().supports_streaming

    @abstractmethod
    def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        stream_callback: Callable[[str | None], None] | None = None,
    ) -> ProviderResponse:
        """Synchronous completion.

        Args:
            messages: List of messages in the conversation.
            tools: List of tool schemas (provider-agnostic format).
            stream_callback: Callback for streaming deltas. Called with None on finish.

        Returns:
            Normalized ProviderResponse.

        Raises:
            ProviderError: On API failure or validation error.
        """
        ...

    @abstractmethod
    async def acomplete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        stream_callback: Callable[[str | None], None] | None = None,
    ) -> ProviderResponse:
        """Asynchronous completion.

        Args:
            messages: List of messages in the conversation.
            tools: List of tool schemas (provider-agnostic format).
            stream_callback: Callback for streaming deltas.

        Returns:
            Normalized ProviderResponse.

        Raises:
            ProviderError: On API failure or validation error.
        """
        ...
