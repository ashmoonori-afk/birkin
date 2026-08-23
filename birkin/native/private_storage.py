"""Cross-platform owner-only permissions for Native authority files."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

_WINDOWS_SID = re.compile(rb"S-\d-\d+(?:-\d+)+")


def harden_private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == "nt":
        _harden_windows_path(path, directory=True)
    else:
        path.chmod(0o700)


def harden_private_file(path: Path) -> None:
    if os.name == "nt":
        _harden_windows_path(path, directory=False)
    else:
        path.chmod(0o600)


def _harden_windows_path(path: Path, *, directory: bool) -> None:
    system_root = os.environ.get("SystemRoot")
    if not system_root:
        raise OSError("cannot locate Windows security tools")
    system = Path(system_root) / "System32"
    identity = _WINDOWS_SID.search(
        _run([str(system / "whoami.exe"), "/user", "/fo", "csv", "/nh"])
    )
    if identity is None:
        raise OSError("cannot identify the Windows Native file owner")
    sid = identity.group().decode("ascii")
    grant = f"*{sid}:(OI)(CI)F" if directory else f"*{sid}:F"
    _ = _run([
        str(system / "icacls.exe"),
        str(path),
        "/inheritance:r",
        "/grant:r",
        grant,
    ])


def _run(command: list[str]) -> bytes:
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
        raise OSError(message or "failed to secure Native authority file")
    return result.stdout
