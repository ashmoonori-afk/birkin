"""Public orchestration facade for terminal policy and session ownership."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import final

from birkin.config_model import Config

from .contracts import TerminalUnsupported
from .service import CommandHandler
from .terminal_policy import TerminalPolicy
from .terminal_process import TerminalProcessFactory, launch_terminal_process
from .terminal_session import (
    MAX_OUTPUT_BYTES,
    MAX_SCREEN_BYTES,
    TerminalEventSink,
    TerminalSessions,
)


@final
class TerminalAuthority:
    """Orchestrate terminal boundary policy and mutable session ownership."""

    max_input_bytes = 4_096
    max_output_bytes = MAX_OUTPUT_BYTES
    max_screen_bytes = MAX_SCREEN_BYTES

    def __init__(
        self,
        *,
        session_id: str,
        workspace_root: Path,
        emit: TerminalEventSink,
        config_loader: Callable[[], Config],
        monotonic: Callable[[], float] = time.monotonic,
        lease_ttl: float = 60.0,
        process_factory: TerminalProcessFactory = launch_terminal_process,
    ) -> None:
        self._policy = TerminalPolicy(
            session_id, workspace_root, emit, config_loader
        )
        self._sessions = TerminalSessions(
            session_id, emit, process_factory, monotonic, lease_ttl
        )

    @property
    def active_process_ids(self) -> tuple[int, ...]:
        return self._sessions.active_process_ids

    def handlers(self) -> Mapping[str, CommandHandler]:
        if not self._policy.supported():
            return {}
        return {
            "terminal.create": self.create,
            "terminal.input": self.input,
            "terminal.resize": self.resize,
            "terminal.signal": self.signal,
            "terminal.close": self.close,
            "terminal.snapshot": self.snapshot,
        }

    def create(self, payload: dict[str, object]) -> dict[str, object]:
        if not self._policy.supported():
            raise TerminalUnsupported(
                "terminal", "this platform has no contained terminal backend"
            )
        return self._sessions.create(self._policy.approve_launch(payload))

    def input(self, payload: dict[str, object]) -> dict[str, object]:
        return self._sessions.input(self._policy.input_intent(payload))

    def resize(self, payload: dict[str, object]) -> dict[str, object]:
        return self._sessions.resize(self._policy.resize_intent(payload))

    def signal(self, payload: dict[str, object]) -> dict[str, object]:
        return self._sessions.signal(self._policy.signal_intent(payload))

    def close(self, payload: dict[str, object]) -> dict[str, object]:
        return self._sessions.close(self._policy.identity(payload, lease=True))

    def snapshot(self, payload: dict[str, object]) -> dict[str, object]:
        return self._sessions.snapshot(self._policy.identity(payload, lease=False))

    def revoke_leases(self) -> None:
        self._sessions.revoke_leases()

    def close_all(self) -> None:
        self._sessions.close_all()
