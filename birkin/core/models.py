"""Core data models for conversation, tools, and provider responses."""

from __future__ import annotations

from dataclasses import dataclass
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
