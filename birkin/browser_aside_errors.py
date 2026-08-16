"""Shared typed errors for Browser Aside boundaries."""

from __future__ import annotations

from typing import final


@final
class BrowserAsideError(RuntimeError):
    """Typed boundary error safe for Browser Aside API responses."""

    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
