"""Canonical Python ownership of native interactive terminal process trees."""

from __future__ import annotations

import os
import secrets
import select
import signal
import struct
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import final

import psutil

from birkin import approvals, config, store
from birkin.config_model import Config

from .approval_projection import approval_item
from .contracts import (
    REDACTION_MARKER,
    ProtocolError,
    TerminalApprovalRequired,
    TerminalLeaseRequired,
    TerminalSequenceRejected,
    TerminalSignalRejected,
    TerminalUnsupported,
)
from .service import CommandHandler

TerminalEventSink = Callable[[str, dict[str, object]], object]

_MAX_INPUT_BYTES = 4_096
_MAX_OUTPUT_BYTES = 16_384
_MAX_SCREEN_BYTES = 65_536
_SIGNAL_NAMES = ("INT", "TERM", "HUP")


@final
@dataclass(frozen=True, slots=True)
class PtySupport:
    """The Unix pseudo-terminal operations an owned process tree needs."""

    open_pty: Callable[[], tuple[int, int]]
    set_nonblocking: Callable[[int], None]
    set_window_size: Callable[[int, int, int], None]


def load_pty_support() -> PtySupport:
    """Bind the Unix PTY primitives, or refuse with a typed capability error."""
    try:
        import fcntl
        import pty
        import termios
    except ModuleNotFoundError as exc:
        raise TerminalUnsupported(
            "terminal",
            "this platform does not provide Unix pseudo-terminals",
        ) from exc

    def set_nonblocking(descriptor: int) -> None:
        flags = fcntl.fcntl(descriptor, fcntl.F_GETFL)
        _ = fcntl.fcntl(descriptor, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    def set_window_size(descriptor: int, columns: int, rows: int) -> None:
        packed = struct.pack("HHHH", rows, columns, 0, 0)
        _ = fcntl.ioctl(descriptor, termios.TIOCSWINSZ, packed)

    return PtySupport(
        open_pty=pty.openpty,
        set_nonblocking=set_nonblocking,
        set_window_size=set_window_size,
    )


def allowed_signals() -> dict[str, signal.Signals]:
    """Project only the process-tree signals this platform actually defines."""
    table: dict[str, signal.Signals] = {}
    for name in _SIGNAL_NAMES:
        value = getattr(signal, f"SIG{name}", None)
        if isinstance(value, signal.Signals):
            table[name] = value
    return table


@dataclass(slots=True)
class _TerminalSession:
    terminal_id: str
    process: subprocess.Popen[bytes]
    master_fd: int
    pty: PtySupport
    cwd: Path
    shell: str
    lease: str | None
    lease_expires_at: float
    input_sequence: int = 0
    output_sequence: int = 0
    screen: bytearray = field(default_factory=bytearray)
    exited_emitted: bool = False


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
        self._config_loader = config_loader
        self._monotonic = monotonic
        self._lease_ttl = lease_ttl
        self._sessions: dict[str, _TerminalSession] = {}
        self._lock = threading.RLock()

    @property
    def active_process_ids(self) -> tuple[int, ...]:
        with self._lock:
            return tuple(
                session.process.pid
                for session in self._sessions.values()
                if session.process.poll() is None
            )

    def handlers(self) -> Mapping[str, CommandHandler]:
        return {
            "terminal.create": self.create,
            "terminal.input": self.input,
            "terminal.resize": self.resize,
            "terminal.signal": self.signal,
            "terminal.close": self.close,
            "terminal.snapshot": self.snapshot,
        }

    def create(self, payload: dict[str, object]) -> dict[str, object]:
        pty = load_pty_support()
        self._keys(payload, required={"actor_kind", "cwd"}, optional={"approval_id"})
        if payload["actor_kind"] != "native_human":
            raise ProtocolError("terminal actor_kind must be native_human")
        cwd = self._cwd(payload["cwd"])
        shell = "/bin/sh"
        approval_id = payload.get("approval_id")
        if approval_id is None:
            proposal: dict[str, object] = approvals.propose(
                category="shell",
                title="Native terminal shell access",
                description="Allow a Python-owned interactive shell for the native human.",
                payload={
                    "command": "/usr/bin/true",
                    "shell": shell,
                    "cwd": str(cwd),
                    "terminal_lease_only": True,
                    "session_id": self._session_id,
                    "actor_kind": "native_human",
                },
                cfg=self._config_loader(),
                origin="native_human",
            )
            approval_id = str(proposal["id"])
            if not proposal.get("auto"):
                pending = store.get_pending(approval_id)
                if pending is not None:
                    projected = approval_item(pending)
                    _ = self._emit(
                        "approval.requested",
                        {"approval_id": approval_id, **projected},
                    )
                raise TerminalApprovalRequired(approval_id)
        if not isinstance(approval_id, str) or not self._approved(
            approval_id, cwd=cwd, shell=shell
        ):
            raise TerminalApprovalRequired(str(approval_id))

        master_fd, slave_fd = pty.open_pty()
        environment = {
            "HOME": os.environ.get("HOME", str(cwd)),
            "LANG": os.environ.get("LANG", "en_US.UTF-8"),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "TERM": "xterm-256color",
            "PS1": "",
            "ENV": "/dev/null",
        }
        try:
            process = subprocess.Popen(
                [shell],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=cwd,
                env=environment,
                start_new_session=True,
                close_fds=True,
            )
        finally:
            os.close(slave_fd)
        pty.set_nonblocking(master_fd)
        terminal_id = f"terminal-{secrets.token_hex(12)}"
        lease = secrets.token_urlsafe(32)
        session = _TerminalSession(
            terminal_id=terminal_id,
            process=process,
            master_fd=master_fd,
            pty=pty,
            cwd=cwd,
            shell=shell,
            lease=lease,
            lease_expires_at=self._monotonic() + self._lease_ttl,
        )
        with self._lock:
            self._sessions[terminal_id] = session
        opened: dict[str, object] = {
            "terminal_id": terminal_id,
            "session_id": self._session_id,
            "actor_kind": "native_human",
            "cwd": str(cwd),
            "shell": shell,
            "pid": process.pid,
            "lease": lease,
            "lease_expires_in": self._lease_ttl,
            "approval_id": approval_id,
            "state": "running",
        }
        _ = self._emit("terminal.opened", {**opened, "lease": REDACTION_MARKER})
        initial = self._read_output(session, timeout=0.1)
        if initial:
            self._output_event(session, initial)
        return opened

    def input(self, payload: dict[str, object]) -> dict[str, object]:
        self._keys(
            payload,
            required={"terminal_id", "lease", "sequence", "data"},
            optional=set(),
        )
        session = self._live_session(payload, require_lease=True)
        sequence = self._positive_integer(payload["sequence"], "sequence")
        if sequence != session.input_sequence + 1:
            raise TerminalSequenceRejected(
                f"terminal input sequence must be {session.input_sequence + 1}"
            )
        data = payload["data"]
        if not isinstance(data, str):
            raise ProtocolError("terminal data must be a string")
        encoded = data.encode("utf-8")
        if not encoded or len(encoded) > _MAX_INPUT_BYTES:
            raise ProtocolError(
                f"terminal input must be between 1 and {_MAX_INPUT_BYTES} bytes"
            )
        self._write_all(session.master_fd, encoded)
        session.input_sequence = sequence
        # Keystrokes are never durable: this journal outlives the session, and
        # what a human types at a terminal includes what they type at a
        # password prompt. The sequence identity is what replay needs.
        _ = self._emit(
            "terminal.input",
            {
                "terminal_id": session.terminal_id,
                "sequence": sequence,
                "redacted": True,
            },
        )
        output = self._read_output(session, timeout=1.0)
        if output:
            self._output_event(session, output)
        self._emit_exit_if_needed(session)
        return {
            "terminal_id": session.terminal_id,
            "input_sequence": sequence,
            "output_sequence": session.output_sequence,
            "output": output.decode("utf-8", errors="replace"),
        }

    def resize(self, payload: dict[str, object]) -> dict[str, object]:
        self._keys(
            payload,
            required={"terminal_id", "lease", "columns", "rows"},
            optional=set(),
        )
        session = self._live_session(payload, require_lease=True)
        columns = self._dimension(payload["columns"], "columns")
        rows = self._dimension(payload["rows"], "rows")
        session.pty.set_window_size(session.master_fd, columns, rows)
        result: dict[str, object] = {
            "terminal_id": session.terminal_id,
            "columns": columns,
            "rows": rows,
        }
        _ = self._emit("terminal.resized", result)
        return result

    def signal(self, payload: dict[str, object]) -> dict[str, object]:
        self._keys(
            payload,
            required={"terminal_id", "lease", "signal"},
            optional=set(),
        )
        session = self._live_session(payload, require_lease=True)
        signals = allowed_signals()
        signal_name = payload["signal"]
        if not isinstance(signal_name, str) or signal_name not in signals:
            raise TerminalSignalRejected("terminal signal must be INT, TERM, or HUP")
        os.killpg(session.process.pid, signals[signal_name])
        result: dict[str, object] = {
            "terminal_id": session.terminal_id,
            "signal": signal_name,
        }
        _ = self._emit("terminal.receipt", {**result, "action": "signal"})
        self._emit_exit_if_needed(session)
        return result

    def close(self, payload: dict[str, object]) -> dict[str, object]:
        self._keys(payload, required={"terminal_id", "lease"}, optional=set())
        session = self._live_session(payload, require_lease=True)
        self._terminate(session, reason="closed")
        result: dict[str, object] = {
            "terminal_id": session.terminal_id,
            "closed": True,
        }
        _ = self._emit("terminal.receipt", {**result, "action": "close"})
        return result

    def snapshot(self, payload: dict[str, object]) -> dict[str, object]:
        self._keys(payload, required={"terminal_id"}, optional=set())
        session = self._session(payload["terminal_id"])
        output = self._read_output(session, timeout=0.0)
        if output:
            self._output_event(session, output)
        self._emit_exit_if_needed(session)
        return {
            "terminal_id": session.terminal_id,
            "cwd": str(session.cwd),
            "screen": bytes(session.screen).decode("utf-8", errors="replace"),
            "output_sequence": session.output_sequence,
            "state": "exited" if session.process.poll() is not None else "running",
            "exit_status": session.process.poll(),
            "read_only": True,
        }

    def revoke_leases(self) -> None:
        with self._lock:
            sessions = tuple(self._sessions.values())
        for session in sessions:
            session.lease = None

    def close_all(self) -> None:
        with self._lock:
            sessions = tuple(self._sessions.values())
        for session in sessions:
            self._terminate(session, reason="authority_closed", emit_exit=False)

    def _approved(self, approval_id: str, *, cwd: Path, shell: str) -> bool:
        if not store.valid_pending_id(approval_id):
            return False
        expected_payload = {
            "command": "/usr/bin/true",
            "shell": shell,
            "cwd": str(cwd),
            "terminal_lease_only": True,
            "session_id": self._session_id,
            "actor_kind": "native_human",
        }
        approval_path = config.pending_dir() / f"{approval_id}.json"
        try:
            with store.file_lock(approval_path):
                record = store.get_pending(approval_id)
                if (
                    not isinstance(record, dict)
                    or record.get("status") != "approved"
                    or record.get("category") != "shell"
                    or record.get("payload") != expected_payload
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

    def _live_session(
        self, payload: dict[str, object], *, require_lease: bool
    ) -> _TerminalSession:
        session = self._session(payload["terminal_id"])
        if session.process.poll() is not None:
            self._emit_exit_if_needed(session)
            raise TerminalLeaseRequired("terminal process has exited")
        if require_lease:
            lease = payload.get("lease")
            if self._monotonic() >= session.lease_expires_at:
                self._terminate(session, reason="lease_expired")
                raise TerminalLeaseRequired("terminal lease expired")
            if (
                not isinstance(lease, str)
                or not lease
                or session.lease is None
                or not secrets.compare_digest(lease, session.lease)
            ):
                raise TerminalLeaseRequired("live terminal lease is required")
        return session

    def _session(self, terminal_id: object) -> _TerminalSession:
        if not isinstance(terminal_id, str):
            raise ProtocolError("terminal_id must be a string")
        with self._lock:
            session = self._sessions.get(terminal_id)
        if session is None:
            raise ProtocolError("terminal session was not found")
        return session

    def _read_output(self, session: _TerminalSession, *, timeout: float) -> bytes:
        chunks = bytearray()
        deadline = self._monotonic() + timeout
        ready, _, _ = select.select([session.master_fd], [], [], timeout)
        while ready and len(chunks) < _MAX_OUTPUT_BYTES:
            try:
                chunk = os.read(
                    session.master_fd,
                    min(4_096, _MAX_OUTPUT_BYTES - len(chunks)),
                )
            except (BlockingIOError, OSError):
                break
            if not chunk:
                break
            chunks.extend(chunk)
            remaining = max(0.0, deadline - self._monotonic())
            ready, _, _ = select.select(
                [session.master_fd], [], [], min(0.05, remaining)
            )
        return bytes(chunks)

    def _output_event(self, session: _TerminalSession, output: bytes) -> None:
        session.output_sequence += 1
        session.screen.extend(output)
        if len(session.screen) > _MAX_SCREEN_BYTES:
            del session.screen[: len(session.screen) - _MAX_SCREEN_BYTES]
        _ = self._emit(
            "terminal.output",
            {
                "terminal_id": session.terminal_id,
                "sequence": session.output_sequence,
                "data": output.decode("utf-8", errors="replace"),
            },
        )

    @staticmethod
    def _owned_processes(
        session: _TerminalSession,
    ) -> tuple[psutil.Process, ...]:
        processes: dict[int, psutil.Process] = {}
        try:
            root = psutil.Process(session.process.pid)
            processes[root.pid] = root
            for child in root.children(recursive=True):
                processes[child.pid] = child
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        for process in psutil.process_iter():
            try:
                if os.getsid(process.pid) == session.process.pid:
                    processes[process.pid] = process
            except (
                ProcessLookupError,
                PermissionError,
                psutil.NoSuchProcess,
                psutil.AccessDenied,
            ):
                continue
        return tuple(processes.values())

    @staticmethod
    def _signal_processes(
        processes: tuple[psutil.Process, ...],
        requested: signal.Signals,
    ) -> tuple[psutil.Process, ...]:
        signalled: list[psutil.Process] = []
        for process in processes:
            try:
                process.send_signal(requested)
            except psutil.NoSuchProcess:
                continue
            signalled.append(process)
        return tuple(signalled)

    def _terminate(
        self,
        session: _TerminalSession,
        *,
        reason: str,
        emit_exit: bool = True,
    ) -> None:
        targets = self._signal_processes(
            self._owned_processes(session),
            signal.SIGTERM,
        )
        if session.process.poll() is None:
            try:
                _ = session.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                session.process.kill()
                _ = session.process.wait(timeout=2)
        descendants = tuple(
            process
            for process in targets
            if process.pid != session.process.pid
        )
        _, alive = psutil.wait_procs(descendants, timeout=2)
        residual = {
            process.pid: process
            for process in (*alive, *self._owned_processes(session))
            if process.pid != session.process.pid
        }
        killed = self._signal_processes(
            tuple(residual.values()),
            signal.SIGKILL,
        )
        _, survivors = psutil.wait_procs(killed, timeout=2)
        if survivors:
            raise subprocess.TimeoutExpired(
                "terminal descendant cleanup",
                timeout=2,
            )
        if emit_exit:
            self._emit_exit_if_needed(session, reason=reason)
        try:
            os.close(session.master_fd)
        except OSError:
            pass
        session.lease = None

    def _emit_exit_if_needed(
        self, session: _TerminalSession, *, reason: str = "exited"
    ) -> None:
        status = session.process.poll()
        if status is None or session.exited_emitted:
            return
        session.exited_emitted = True
        _ = self._emit(
            "terminal.exited",
            {
                "terminal_id": session.terminal_id,
                "exit_status": status,
                "reason": reason,
            },
        )

    @staticmethod
    def _write_all(fd: int, data: bytes) -> None:
        view = memoryview(data)
        while view:
            try:
                written = os.write(fd, view)
            except BlockingIOError:
                _, writable, _ = select.select([], [fd], [], 1.0)
                if not writable:
                    raise ProtocolError("terminal input write timed out")
                continue
            view = view[written:]

    @staticmethod
    def _keys(
        payload: dict[str, object], *, required: set[str], optional: set[str]
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
