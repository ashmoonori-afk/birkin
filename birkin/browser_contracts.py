"""Typed contracts shared by optional Birkin browser adapters."""

from __future__ import annotations

from dataclasses import dataclass


class BrowserError(RuntimeError):
    """Base class for browser-surface failures."""


class BrowserUnavailableError(BrowserError):
    """The optional browser runtime is not installed or cannot start."""


class BrowserPolicyViolation(BrowserError, PermissionError):
    """A browser action was refused by the shared sandbox policy."""


@dataclass(frozen=True, slots=True)
class ConsoleMessage:
    type: str
    text: str


@dataclass(frozen=True, slots=True)
class NetworkEvent:
    kind: str
    method: str
    url: str
    status: int | None
    resource_type: str
