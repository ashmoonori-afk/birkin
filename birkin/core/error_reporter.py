"""Non-fatal error reporter — surfaces silent failures to users."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

logger = logging.getLogger(__name__)


class ErrorSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class UserError:
    severity: ErrorSeverity
    component: str
    message: str
    detail: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


class ErrorReporter:
    """Collects non-fatal errors during a session for user notification.

    Usage::

        reporter = ErrorReporter()
        reporter.add(ErrorSeverity.WARNING, "memory", "Save failed")
        errors = reporter.drain()
    """

    def __init__(self) -> None:
        self._pending: list[UserError] = []

    def add(self, severity: ErrorSeverity, component: str, message: str, detail: str = "") -> None:
        error = UserError(severity=severity, component=component, message=message, detail=detail)
        self._pending.append(error)
        log_level = logging.WARNING if severity != ErrorSeverity.INFO else logging.INFO
        logger.log(log_level, "[%s] %s: %s", component, severity.value, message)

    def drain(self) -> list[UserError]:
        """Return and clear all pending errors."""
        errors = self._pending.copy()
        self._pending.clear()
        return errors

    def has_errors(self) -> bool:
        return len(self._pending) > 0

    def to_chat_metadata(self) -> list[dict]:
        """Format for SSE chat response metadata."""
        return [{"severity": e.severity.value, "component": e.component, "message": e.message} for e in self._pending]
