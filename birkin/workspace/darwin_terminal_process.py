"""Darwin terminal processes isolated in launchd resource coalitions."""

from __future__ import annotations

import os
import re
import signal
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import final

from .darwin_coalition import (
    resource_coalition_id,
    terminate_resource_coalition,
)

_LAUNCHCTL = "/bin/launchctl"
_SANDBOX_EXEC = "/usr/bin/sandbox-exec"
_TERMINAL_SANDBOX_PROFILE = (
    "(version 1)(allow default)"
    "(deny mach-lookup)(deny network*)(deny ipc*)"
)


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
    script = 'cd "$1" && exec "$2" <"$3" >"$3" 2>&1'
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
    ]
    submitted = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if submitted.returncode != 0:
        raise OSError(
            submitted.stderr.strip() or "launchctl could not submit terminal"
        )
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
        return DarwinTerminalProcess(
            pid=pid,
            label=label,
            coalition_id=coalition_id,
        )
    except (OSError, subprocess.SubprocessError):
        _ = subprocess.run(
            [_LAUNCHCTL, "remove", label],
            capture_output=True,
            timeout=5,
            check=False,
        )
        raise


def terminate_darwin_terminal(process: DarwinTerminalProcess) -> None:
    """Remove the launchd job and kill every member of its resource coalition."""
    _ = subprocess.run(
        [_LAUNCHCTL, "remove", process.label],
        capture_output=True,
        timeout=5,
        check=False,
    )
    terminate_resource_coalition(process.coalition_id)
    process.mark_terminated()
