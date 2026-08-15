"""Least-privilege mutation authority for one Computer Use session."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(slots=True)
class SessionCapability:
    session_id: str
    actor: str
    source: str
    allowed_operations: frozenset[str]
    allowed_apps: frozenset[str] | None = None
    denied_apps: frozenset[str] = field(default_factory=frozenset)
    allowed_windows: frozenset[str] | None = None
    denied_windows: frozenset[str] = field(default_factory=frozenset)
    max_actions: int = 200
    expires_at: float | None = None
    clock: Callable[[], float] = time.monotonic
    actions_used: int = 0

    def app_allowed(self, native_identity: str) -> bool:
        if native_identity in self.denied_apps:
            return False
        return self.allowed_apps is None or native_identity in self.allowed_apps

    def window_allowed(self, native_window_id: str) -> bool:
        if native_window_id in self.denied_windows:
            return False
        return self.allowed_windows is None or native_window_id in self.allowed_windows

    def authorize(
        self,
        *,
        session_id: str,
        operation: str,
        app_identity: str,
        native_window_id: str,
    ) -> str | None:
        if session_id != self.session_id:
            return "cross_session_ref"
        if self.expires_at is not None and self.clock() >= self.expires_at:
            return "session_capability_expired"
        if operation not in self.allowed_operations:
            return "session_capability_denied"
        if not self.app_allowed(app_identity):
            return "app_policy_denied"
        if not self.window_allowed(native_window_id):
            return "window_policy_denied"
        if self.actions_used >= self.max_actions:
            return "rate_limited"
        return None

    def consume(self) -> None:
        self.actions_used += 1
