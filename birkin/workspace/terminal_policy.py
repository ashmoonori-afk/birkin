"""Typed terminal command parsing, platform policy, and shell approval."""

from __future__ import annotations

import os
import signal
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import final

from birkin import approvals, config, store
from birkin.config_model import Config

from .approval_projection import approval_item
from .contracts import (
    ProtocolError,
    TerminalApprovalRequired,
    TerminalSignalRejected,
)

_SIGNAL_NAMES = ("INT", "TERM", "HUP")


@dataclass(frozen=True, slots=True)
class ApprovedTerminalLaunch:
    shell: Path
    cwd: Path
    environment: dict[str, str]
    approval_id: str


@dataclass(frozen=True, slots=True)
class TerminalIdentity:
    terminal_id: str
    lease: str | None


@dataclass(frozen=True, slots=True)
class TerminalInputIntent:
    identity: TerminalIdentity
    sequence: int
    data: bytes


@dataclass(frozen=True, slots=True)
class TerminalResizeIntent:
    identity: TerminalIdentity
    columns: int
    rows: int


@dataclass(frozen=True, slots=True)
class TerminalSignalIntent:
    identity: TerminalIdentity
    name: str


def allowed_signals() -> dict[str, signal.Signals]:
    """Project only process-tree signals defined by the interpreter."""
    table: dict[str, signal.Signals] = {}
    for name in _SIGNAL_NAMES:
        value = getattr(signal, f"SIG{name}", None)
        if isinstance(value, signal.Signals):
            table[name] = value
    return table


@final
class TerminalPolicy:
    """Parse untrusted terminal commands and consume exact shell approvals."""

    def __init__(
        self,
        session_id: str,
        workspace_root: Path,
        emit: Callable[[str, dict[str, object]], object],
        config_loader: Callable[[], Config],
    ) -> None:
        self._session_id = session_id
        self._workspace_root = workspace_root.expanduser().resolve()
        self._emit = emit
        self._config_loader = config_loader

    def supported(self) -> bool:
        darwin, windows = self._platform_flags()
        if not windows:
            return darwin
        from ._windows_conpty_abi import conpty_supported

        return conpty_supported()

    def approve_launch(self, payload: dict[str, object]) -> ApprovedTerminalLaunch:
        self._keys(payload, {"actor_kind", "cwd"}, {"approval_id"})
        if payload["actor_kind"] != "native_human":
            raise ProtocolError("terminal actor_kind must be native_human")
        cwd = self._cwd(payload["cwd"])
        shell = self._shell_path()
        approval_id = payload.get("approval_id")
        if approval_id is None:
            proposal = approvals.propose(
                category="shell",
                title="Native terminal shell access",
                description=(
                    "Allow a Python-owned interactive shell for the native human."
                ),
                payload=self._approval_payload(shell, cwd),
                cfg=self._config_loader(),
                origin="native_human",
            )
            proposed_id = proposal.get("id")
            if not isinstance(proposed_id, str):
                raise ProtocolError("terminal approval proposal id is invalid")
            approval_id = proposed_id
            if not proposal.get("auto"):
                pending = store.get_pending(approval_id)
                if pending is not None:
                    _ = self._emit(
                        "approval.requested",
                        {"approval_id": approval_id, **approval_item(pending)},
                    )
                raise TerminalApprovalRequired(approval_id)
        if not isinstance(approval_id, str) or not self._approved(
            approval_id, cwd, shell
        ):
            raise TerminalApprovalRequired(str(approval_id))
        return ApprovedTerminalLaunch(
            shell, cwd, self._environment(cwd), approval_id
        )

    def input_intent(self, payload: dict[str, object]) -> TerminalInputIntent:
        self._keys(payload, {"terminal_id", "lease", "sequence", "data"}, set())
        sequence = self._positive_integer(payload["sequence"], "sequence")
        data = payload["data"]
        if not isinstance(data, str):
            raise ProtocolError("terminal data must be a string")
        encoded = data.encode("utf-8")
        if not encoded or len(encoded) > 4_096:
            raise ProtocolError("terminal input must be between 1 and 4096 bytes")
        return TerminalInputIntent(self._identity_values(payload), sequence, encoded)

    def resize_intent(self, payload: dict[str, object]) -> TerminalResizeIntent:
        self._keys(payload, {"terminal_id", "lease", "columns", "rows"}, set())
        return TerminalResizeIntent(
            self._identity_values(payload),
            self._dimension(payload["columns"], "columns"),
            self._dimension(payload["rows"], "rows"),
        )

    def signal_intent(self, payload: dict[str, object]) -> TerminalSignalIntent:
        self._keys(payload, {"terminal_id", "lease", "signal"}, set())
        name = payload["signal"]
        _, windows = self._platform_flags()
        accepted = {"INT"} if windows else set(allowed_signals())
        if not isinstance(name, str) or name not in accepted:
            raise TerminalSignalRejected("terminal signal is unavailable")
        return TerminalSignalIntent(self._identity_values(payload), name)

    def identity(
        self,
        payload: dict[str, object],
        *,
        lease: bool,
    ) -> TerminalIdentity:
        required = {"terminal_id", "lease"} if lease else {"terminal_id"}
        self._keys(payload, required, set())
        return self._identity_values(payload)

    @staticmethod
    def _identity_values(payload: dict[str, object]) -> TerminalIdentity:
        terminal_id = payload["terminal_id"]
        if not isinstance(terminal_id, str):
            raise ProtocolError("terminal_id must be a string")
        lease_value = payload.get("lease")
        return TerminalIdentity(
            terminal_id,
            lease_value if isinstance(lease_value, str) else None,
        )

    def _approved(self, approval_id: str, cwd: Path, shell: Path) -> bool:
        if not store.valid_pending_id(approval_id):
            return False
        approval_path = config.pending_dir() / f"{approval_id}.json"
        try:
            with store.file_lock(approval_path):
                record = store.get_pending(approval_id)
                if (
                    not isinstance(record, dict)
                    or record.get("status") != "approved"
                    or record.get("category") != "shell"
                    or record.get("payload") != self._approval_payload(shell, cwd)
                ):
                    return False
                _ = store.resolve_pending(approval_id, "consumed")
        except store.FileLockTimeout:
            return False
        return True

    def _cwd(self, value: object) -> Path:
        if not isinstance(value, str):
            raise ProtocolError("terminal cwd must be a string")
        cwd = Path(value).expanduser().resolve()
        try:
            _ = cwd.relative_to(self._workspace_root)
        except ValueError as exc:
            raise ProtocolError("terminal cwd is outside the workspace") from exc
        if not cwd.is_dir():
            raise ProtocolError("terminal cwd does not exist")
        return cwd

    def _shell_path(self) -> Path:
        darwin, _ = self._platform_flags()
        if darwin:
            return Path("/bin/sh")
        root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        return (root / "System32" / "cmd.exe").resolve(strict=True)

    def _environment(self, cwd: Path) -> dict[str, str]:
        darwin, windows = self._platform_flags()
        if windows:
            return {**os.environ, "TERM": "xterm-256color", "PROMPT": ""}
        if darwin:
            return {
                "HOME": os.environ.get("HOME", str(cwd)),
                "LANG": os.environ.get("LANG", "en_US.UTF-8"),
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "TERM": "xterm-256color",
                "PS1": "",
                "ENV": "/dev/null",
            }
        return {}

    def _approval_payload(self, shell: Path, cwd: Path) -> dict[str, object]:
        return {
            "command": "/usr/bin/true",
            "shell": str(shell),
            "cwd": str(cwd),
            "terminal_lease_only": True,
            "session_id": self._session_id,
            "actor_kind": "native_human",
        }

    @staticmethod
    def _platform_flags() -> tuple[bool, bool]:
        compatibility = sys.modules.get("birkin.workspace.owned_terminal")
        values = vars(compatibility) if compatibility is not None else {}
        return (
            values.get("_DARWIN", sys.platform == "darwin") is True,
            values.get("_WINDOWS", sys.platform == "win32") is True,
        )

    @staticmethod
    def _keys(
        payload: dict[str, object], required: set[str], optional: set[str]
    ) -> None:
        if not required <= set(payload) or set(payload) - required - optional:
            raise ProtocolError("terminal payload keys do not match the contract")

    @staticmethod
    def _positive_integer(value: object, label: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ProtocolError(f"terminal {label} must be a positive integer")
        return value

    @classmethod
    def _dimension(cls, value: object, label: str) -> int:
        result = cls._positive_integer(value, label)
        if result > 1_000:
            raise ProtocolError(f"terminal {label} exceeds 1000")
        return result
