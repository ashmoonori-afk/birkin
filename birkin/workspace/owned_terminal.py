"""Canonical Python ownership of native interactive terminal process trees."""

from __future__ import annotations

import os
import secrets
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import final

from birkin.config_model import Config

from .contracts import (
    REDACTION_MARKER,
    ProtocolError,
    TerminalApprovalRequired as TerminalApprovalRequired,
    TerminalLeaseRequired as TerminalLeaseRequired,
    TerminalSequenceRejected as TerminalSequenceRejected,
    TerminalSignalRejected as TerminalSignalRejected,
    TerminalUnsupported,
)
from .darwin_terminal_process import (
    DarwinTerminalProcess as DarwinTerminalProcess,
    launch_darwin_terminal as launch_darwin_terminal,
    terminate_darwin_terminal as terminate_darwin_terminal,
)
from .owned_terminal_access import TERMINAL_SHELL, TerminalAccessAuthority
from .owned_terminal_commands import TerminalCommands
from .owned_terminal_pty import (
    MAX_INPUT_BYTES as _MAX_INPUT_BYTES,
    MAX_OUTPUT_BYTES as _MAX_OUTPUT_BYTES,
    MAX_SCREEN_BYTES as _MAX_SCREEN_BYTES,
    PtySupport as PtySupport,
    TerminalSession as _TerminalSession,
    allowed_signals as allowed_signals,
    load_pty_support as load_pty_support,
)
from .owned_terminal_session import (
    TerminalEventSink as TerminalEventSink,
    TerminalSessionOwner,
    validate_keys,
)
from .service import CommandHandler

_DARWIN = sys.platform == "darwin"

__all__ = [
    "DarwinTerminalProcess",
    "PtySupport",
    "TerminalApprovalRequired",
    "TerminalAuthority",
    "TerminalEventSink",
    "TerminalLeaseRequired",
    "TerminalSequenceRejected",
    "TerminalSignalRejected",
    "TerminalUnsupported",
    "allowed_signals",
    "launch_darwin_terminal",
    "load_pty_support",
    "terminate_darwin_terminal",
]


@final
class TerminalAuthority:
    """Own PTYs, process groups, leases, policy proposals, and event receipts."""

    max_input_bytes = _MAX_INPUT_BYTES
    max_output_bytes = _MAX_OUTPUT_BYTES
    max_screen_bytes = _MAX_SCREEN_BYTES

    def __init__(
        self,
        *,
        session_id: str,
        workspace_root: Path,
        emit: TerminalEventSink,
        config_loader: Callable[[], Config],
        monotonic: Callable[[], float] = time.monotonic,
        lease_ttl: float = 60.0,
    ) -> None:
        if lease_ttl <= 0 or lease_ttl > 300:
            raise ValueError("terminal lease TTL must be within 300 seconds")
        self._session_id = session_id
        self._workspace_root = workspace_root.expanduser().resolve()
        self._emit = emit
        self._monotonic = monotonic
        self._lease_ttl = lease_ttl
        self._access = TerminalAccessAuthority(
            session_id,
            self._workspace_root,
            config_loader,
        )
        self._sessions = TerminalSessionOwner(emit, monotonic)
        self._commands = TerminalCommands(self._sessions)

    @property
    def active_process_ids(self) -> tuple[int, ...]:
        return self._sessions.active_process_ids

    def handlers(self) -> Mapping[str, CommandHandler]:
        if not _DARWIN:
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
        if not _DARWIN:
            raise TerminalUnsupported(
                "terminal",
                "secure terminal process containment requires macOS",
            )
        pty = load_pty_support()
        validate_keys(
            payload,
            required={"actor_kind", "cwd"},
            optional={"approval_id"},
        )
        if payload["actor_kind"] != "native_human":
            raise ProtocolError("terminal actor_kind must be native_human")
        cwd = self._access.resolve_cwd(payload["cwd"])
        approval_id = self._access.authorize(
            cwd,
            payload.get("approval_id"),
            self._emit,
        )
        master_fd, slave_fd = pty.open_pty()
        environment = {
            "HOME": os.environ.get("HOME", str(cwd)),
            "LANG": os.environ.get("LANG", "en_US.UTF-8"),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "TERM": "xterm-256color",
            "PS1": "",
            "ENV": "/dev/null",
        }
        process: DarwinTerminalProcess | None = None
        try:
            process = launch_darwin_terminal(
                shell_path=TERMINAL_SHELL,
                cwd=cwd,
                environment=environment,
                slave_path=os.ttyname(slave_fd),
                label=f"com.birkin.terminal.{secrets.token_hex(16)}",
            )
        finally:
            os.close(slave_fd)
            if process is None:
                os.close(master_fd)
        if process is None:
            raise OSError("terminal process did not launch")
        pty.set_nonblocking(master_fd)
        terminal_id = f"terminal-{secrets.token_hex(12)}"
        lease = secrets.token_urlsafe(32)
        session = _TerminalSession(
            terminal_id=terminal_id,
            process=process,
            master_fd=master_fd,
            pty=pty,
            cwd=cwd,
            lease=lease,
            lease_expires_at=self._monotonic() + self._lease_ttl,
            monotonic=self._monotonic,
        )
        self._sessions.register(session)
        opened: dict[str, object] = {
            "terminal_id": terminal_id,
            "session_id": self._session_id,
            "actor_kind": "native_human",
            "cwd": str(cwd),
            "shell": TERMINAL_SHELL,
            "pid": process.pid,
            "lease": lease,
            "lease_expires_in": self._lease_ttl,
            "approval_id": approval_id,
            "state": "running",
        }
        _ = self._emit("terminal.opened", {**opened, "lease": REDACTION_MARKER})
        try:
            _ = self._sessions.capture_output(session, timeout=0.1)
        except (OSError, ProtocolError):
            self._sessions.backend_failed(session)
            raise
        return opened

    def input(self, payload: dict[str, object]) -> dict[str, object]:
        return self._commands.input(payload)

    def resize(self, payload: dict[str, object]) -> dict[str, object]:
        return self._commands.resize(payload)

    def signal(self, payload: dict[str, object]) -> dict[str, object]:
        return self._commands.signal(payload)

    def close(self, payload: dict[str, object]) -> dict[str, object]:
        return self._commands.close(payload)

    def snapshot(self, payload: dict[str, object]) -> dict[str, object]:
        return self._commands.snapshot(payload)

    def revoke_leases(self) -> None:
        self._sessions.revoke_leases()

    def close_all(self) -> None:
        self._sessions.close_all()
