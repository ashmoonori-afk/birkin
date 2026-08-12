"""Private atomic storage for voice daemon control state."""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
from dataclasses import asdict
from pathlib import Path

from birkin.config import birkin_home

from .daemon_state import DaemonState

_WINDOWS_SID = re.compile(rb"S-\d-\d+(?:-\d+)+")


def daemon_paths() -> tuple[Path, Path]:
    directory = birkin_home() / "voice"
    return directory / "daemon.json", directory / "daemon.log"


def claim_state(path: Path, state: DaemonState) -> None:
    temporary = _write_state_file(path, state)
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_state(path: Path) -> DaemonState:
    return DaemonState.from_mapping(
        json.loads(path.read_text(encoding="utf-8"))
    )


def update_state(path: Path, state: DaemonState) -> bool:
    try:
        current = load_state(path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return False
    if current.instance_id != state.instance_id:
        return False
    temporary = _write_state_file(path, state)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def _write_state_file(path: Path, state: DaemonState) -> Path:
    _harden_state_directory(path.parent)
    temporary = path.with_name(
        f".{path.name}.{secrets.token_hex(8)}.tmp"
    )
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(asdict(state), handle, sort_keys=True)
            handle.write("\n")
        if os.name != "nt":
            os.chmod(temporary, 0o600)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def _harden_state_directory(directory: Path) -> None:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(directory, 0o700)
        return
    _harden_windows_directory(directory)


def _harden_windows_directory(directory: Path) -> None:
    system_root = os.environ.get("SystemRoot")
    if not system_root:
        raise OSError("cannot locate Windows security tools")
    whoami = Path(system_root) / "System32" / "whoami.exe"
    icacls = Path(system_root) / "System32" / "icacls.exe"
    identity = _WINDOWS_SID.search(
        _run_windows_security_command(
            [str(whoami), "/user", "/fo", "csv", "/nh"]
        )
    )
    if identity is None:
        raise OSError("cannot identify the Windows voice state owner")
    sid = identity.group().decode("ascii")
    _run_windows_security_command([str(icacls), str(directory), "/reset"])
    _run_windows_security_command(
        [
            str(icacls),
            str(directory),
            "/inheritance:r",
            "/grant:r",
            f"*{sid}:(OI)(CI)F",
        ]
    )


def _run_windows_security_command(command: list[str]) -> bytes:
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        message = (
            result.stderr.decode(errors="replace").strip()
            or result.stdout.decode(errors="replace").strip()
        )
        raise OSError(message or "failed to secure voice state directory")
    return result.stdout


def remove_state(path: Path, instance_id: str) -> bool:
    try:
        current = load_state(path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return False
    if current.instance_id != instance_id:
        return False
    path.unlink(missing_ok=True)
    return True
