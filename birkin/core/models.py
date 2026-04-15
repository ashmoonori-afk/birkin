"""Core data models for conversation, tools, and provider responses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class Message:
    """A single message in a conversation."""

    role: str  # "system" | "user" | "assistant" | "tool"
    content: str
    tool_calls: Optional[list[dict[str, Any]]] = None
    tool_call_id: Optional[str] = None


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
    content: Optional[str] = None
    tool_call: Optional[ToolCall] = None
    stop_reason: Optional[str] = None


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
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 1.0
    max_tokens: Optional[int] = None


@dataclass(frozen=True)
class AgentResponse:
    """Response from an agent's completion."""

    message: Message
    usage: dict[str, int] = field(default_factory=dict)
    stop_reason: Optional[str] = None
