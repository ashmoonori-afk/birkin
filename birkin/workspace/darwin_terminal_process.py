"""Darwin terminal processes isolated in launchd resource coalitions."""

from __future__ import annotations

import os
import re
import secrets
import select
import signal
import subprocess
import tempfile
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import final

from ._darwin_pty import (
    DarwinPtyDescriptor,
    PtySupport as PtySupport,
    load_pty_support as load_pty_support,
    open_darwin_pty,
)
from .contracts import TerminalSignalRejected
from .darwin_coalition import (
    DarwinCoalitionCleanupError,
    resource_coalition_id,
    terminate_resource_coalition,
)

_LAUNCHCTL = "/bin/launchctl"
_SANDBOX_EXEC = "/usr/bin/sandbox-exec"
_TERMINAL_SANDBOX_PROFILE = "(version 1)(allow default)(deny mach-lookup)(deny network*)(deny ipc*)(deny signal)"
_SIGNAL_NAMES = ("INT", "TERM", "HUP")


def darwin_signals() -> dict[str, signal.Signals]:
    """Return only terminal signals defined by the running interpreter."""
    table: dict[str, signal.Signals] = {}
    for name in _SIGNAL_NAMES:
        value = getattr(signal, f"SIG{name}", None)
        if isinstance(value, signal.Signals):
            table[name] = value
    return table


@final
@dataclass(slots=True)
class DarwinTerminalProcess:
    """A launchd job whose descendants share one kernel resource coalition."""

    pid: int
    label: str
    coalition_id: int
    _returncode: int | None = field(default=None, init=False)

    def poll(self) -> int | None:
        if self._returncode is not None:
            return self._returncode
        if resource_coalition_id(self.pid) != self.coalition_id:
            self._returncode = 0
        return self._returncode

    def mark_terminated(self) -> None:
        self._returncode = -signal.SIGKILL


def launch_darwin_terminal(
    *,
    shell_path: str,
    cwd: Path,
    environment: dict[str, str],
    slave_path: str,
    label: str,
) -> DarwinTerminalProcess:
    """Launch one PTY shell in a terminal-unique launchd resource coalition."""
    with tempfile.TemporaryDirectory(
        prefix="birkin-terminal-",
        dir="/private/tmp",
    ) as readiness_root:
        ready_path = Path(readiness_root) / "ready"
        os.mkfifo(ready_path, mode=0o600)
        ready_fd = os.open(ready_path, os.O_RDWR | os.O_NONBLOCK)
        script = (
            'cd "$1" && exec 0<"$3" 1>"$3" 2>&1 && '
            'printf 1 >"$4" && exec "$2"'
        )
        command = [
            _LAUNCHCTL,
            "submit",
            "-l",
            label,
            "--",
            "/usr/bin/env",
            *(f"{key}={value}" for key, value in sorted(environment.items())),
            _SANDBOX_EXEC,
            "-p",
            _TERMINAL_SANDBOX_PROFILE,
            "/bin/sh",
            "-c",
            script,
            "birkin-terminal",
            str(cwd),
            shell_path,
            slave_path,
            str(ready_path),
        ]
        try:
            submitted = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as submit_error:
            remove_error = _remove_launchd_job(label)
            os.close(ready_fd)
            if remove_error is not None:
                raise remove_error from submit_error
            raise
        if submitted.returncode != 0:
            os.close(ready_fd)
            raise OSError(
                submitted.stderr.strip()
                or "launchctl could not submit terminal"
            )
        process: DarwinTerminalProcess | None = None
        try:
            listed = subprocess.run(
                [_LAUNCHCTL, "list", label],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            match = re.search(r'"PID"\s*=\s*(\d+)', listed.stdout)
            if match is None:
                raise OSError("launchctl terminal PID is unavailable")
            pid = int(match.group(1))
            coalition_id = resource_coalition_id(pid)
            if coalition_id is None:
                raise OSError("launchctl terminal coalition is unavailable")
            owner_coalition = resource_coalition_id(os.getpid())
            if owner_coalition is None or coalition_id == owner_coalition:
                raise OSError("launchctl did not isolate the terminal coalition")
            process = DarwinTerminalProcess(
                pid=pid,
                label=label,
                coalition_id=coalition_id,
            )
            readable, _, _ = select.select([ready_fd], [], [], 5)
            if readable != [ready_fd] or os.read(ready_fd, 1) != b"1":
                raise OSError("launchctl terminal PTY did not become ready")
            return process
        except (OSError, subprocess.SubprocessError) as startup_error:
            remove_error = _remove_launchd_job(label)
            coalition_error: OSError | DarwinCoalitionCleanupError | None = None
            if process is not None:
                try:
                    terminate_resource_coalition(process.coalition_id)
                except (OSError, DarwinCoalitionCleanupError) as exc:
                    coalition_error = exc
            if coalition_error is not None:
                raise coalition_error from startup_error
            if remove_error is not None:
                raise remove_error from startup_error
            raise
        finally:
            os.close(ready_fd)


@final
class DarwinOwnedTerminalProcess:
    """Own a Darwin PTY descriptor and its isolated launchd coalition."""

    def __init__(
        self,
        process: DarwinTerminalProcess,
        descriptor: DarwinPtyDescriptor,
    ) -> None:
        self.pid = process.pid
        self._process = process
        self._descriptor = descriptor
        self._closed = False
        self._lock = threading.Lock()

    def poll(self) -> int | None:
        return self._process.poll()

    def read(self, max_bytes: int, timeout: float | None) -> bytes:
        return self._descriptor.read(max_bytes, timeout)

    def write(self, data: bytes, timeout: float) -> None:
        self._descriptor.write(data, timeout)

    def resize(self, columns: int, rows: int) -> None:
        self._descriptor.resize(columns, rows)

    def signal(self, name: str) -> None:
        signals = darwin_signals()
        if name not in signals:
            raise TerminalSignalRejected("terminal signal must be INT, TERM, or HUP")
        os.killpg(self.pid, signals[name])

    def close(self, exit_code: int = 1) -> None:
        del exit_code
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            terminate_darwin_terminal(self._process)
        finally:
            self._descriptor.close()


def launch_darwin_terminal_process(
    shell_path: Path,
    cwd: Path,
    environment: Mapping[str, str],
    columns: int,
    rows: int,
) -> DarwinOwnedTerminalProcess:
    """Launch and transfer a Darwin PTY plus coalition to one owner."""
    pair = open_darwin_pty()
    descriptor: DarwinPtyDescriptor | None = None
    process: DarwinTerminalProcess | None = None
    try:
        slave_path = pair.slave_path
        descriptor = pair.transfer(columns, rows)
        process = launch_darwin_terminal(
            shell_path=str(shell_path),
            cwd=cwd,
            environment=dict(environment),
            slave_path=slave_path,
            label=f"com.birkin.terminal.{secrets.token_hex(16)}",
        )
        return DarwinOwnedTerminalProcess(process, descriptor)
    finally:
        pair.close()
        if process is None and descriptor is not None:
            descriptor.close()


def terminate_darwin_terminal(process: DarwinTerminalProcess) -> None:
    """Remove the launchd job and kill every member of its resource coalition."""
    remove_error = _remove_launchd_job(process.label)
    try:
        terminate_resource_coalition(process.coalition_id)
    except (OSError, DarwinCoalitionCleanupError) as coalition_error:
        if remove_error is not None:
            raise coalition_error from remove_error
        raise
    process.mark_terminated()
    if remove_error is not None:
        raise remove_error


def _remove_launchd_job(
    label: str,
) -> OSError | subprocess.SubprocessError | None:
    try:
        removed = subprocess.run(
            [_LAUNCHCTL, "remove", label],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return exc
    if removed.returncode not in {0, 3}:
        return OSError(
            removed.stderr.strip() or "launchctl could not remove terminal"
        )
    return None
