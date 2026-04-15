"""Core data models for conversation, tools, and provider responses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterator


@dataclass(frozen=True)
class Message:
    """A single message in a conversation."""

    role: str  # "system" | "user" | "assistant" | "tool"
    content: str
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None


@dataclass(frozen=True)
class ToolCall:
    """A tool invocation from the assistant."""

    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    """The result of executing a tool."""

    tool_call_id: str
    name: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class StreamDelta:
    """A delta (partial update) in a streaming response."""

    type: str  # "text_delta" | "tool_call_start" | "tool_call_delta" | "stop"
    content: str | None = None
    tool_call: ToolCall | None = None
    stop_reason: str | None = None


@dataclass
class ConversationContext:
    """State of a conversation for windowing and replay."""

    messages: list[Message] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    max_context_messages: int = 100


@dataclass(frozen=True)
class ProviderConfig:
    """Configuration for a provider."""

    name: str  # "anthropic" | "openai"
    model: str
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 1.0
    max_tokens: int | None = None


@dataclass(frozen=True)
class AgentResponse:
    """Response from an agent's completion."""

    message: Message
    usage: dict[str, int] = field(default_factory=dict)
    stop_reason: str | None = None
