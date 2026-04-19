"""Core error types for Birkin."""

from __future__ import annotations

from enum import Enum
from typing import Optional


class BirkinError(Exception):
    """Base exception for all Birkin errors."""


class ProviderErrorKind(Enum):
    """Classification of provider errors for retry/backoff logic."""

    API = "api"
    RATE_LIMIT = "rate_limit"
    AUTH = "auth"
    CONTEXT_OVERFLOW = "context_overflow"
    SERVER = "server"
    NETWORK = "network"
    UNKNOWN = "unknown"


class ProviderError(BirkinError):
    """Exception raised by provider operations."""

    def __init__(
        self,
        message: str,
        kind: ProviderErrorKind = ProviderErrorKind.UNKNOWN,
        original_error: Optional[Exception] = None,
    ) -> None:
        self.message = message
        self.kind = kind
        self.original_error = original_error
        super().__init__(message)


class SessionError(BirkinError):
    """Error related to session management."""


class ToolExecutionError(BirkinError):
    """Error during tool execution."""

    def __init__(self, tool_name: str, message: str) -> None:
        self.tool_name = tool_name
        self.message = message
        super().__init__(f"Tool {tool_name} failed: {message}")
