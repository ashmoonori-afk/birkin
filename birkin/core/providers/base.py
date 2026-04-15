"""Abstract provider interface and shared data types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Optional

from birkin.core.errors import ProviderError, ProviderErrorKind
from birkin.core.models import Message, ToolCall

# Re-export so existing `from birkin.core.providers.base import ...` still works.
__all__ = [
    "TokenUsage",
    "ModelCapabilities",
    "ProviderResponse",
    "ProviderError",
    "ProviderErrorKind",
    "Provider",
]


@dataclass(frozen=True)
class TokenUsage:
    """Token usage statistics from a provider."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int = 0

    def __post_init__(self) -> None:
        if self.total_tokens == 0:
            object.__setattr__(self, "total_tokens", self.prompt_tokens + self.completion_tokens)


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

    content: Optional[str] = None
    tool_calls: Optional[list[ToolCall]] = None
    usage: Optional[TokenUsage] = None
    stop_reason: Optional[str] = None
    model: Optional[str] = None


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
        tools: Optional[list[dict[str, Any]]] = None,
        stream_callback: Optional[Callable[[Optional[str]], None]] = None,
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
        tools: Optional[list[dict[str, Any]]] = None,
        stream_callback: Optional[Callable[[Optional[str]], None]] = None,
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
