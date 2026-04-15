"""Core error types for Birkin."""

from __future__ import annotations

from typing import Optional


class BirkinError(Exception):
    """Base exception for all Birkin errors."""

    pass


class ProviderError(BirkinError):
    """Error from an LLM provider."""

    def __init__(self, message: str, provider: Optional[str] = None) -> None:
        self.message = message
        self.provider = provider
        super().__init__(message)


class SessionError(BirkinError):
    """Error related to session management."""

    pass


class ToolExecutionError(BirkinError):
    """Error during tool execution."""

    def __init__(self, tool_name: str, message: str) -> None:
        self.tool_name = tool_name
        self.message = message
        super().__init__(f"Tool {tool_name} failed: {message}")
