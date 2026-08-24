"""Cross-platform owner-only permissions for Native authority files."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from birkin.native import private_storage_windows as _windows

_windows_owner_sid = _windows.windows_owner_sid

__all__ = [
    "create_private_temp",
    "harden_private_directory",
    "harden_private_file",
]


def create_private_temp(
    directory: Path,
    *,
    prefix: str,
) -> tuple[int, str]:
    if os.name == "nt":
        return _windows.create_windows_private_temp(directory, prefix=prefix)
    descriptor, name = tempfile.mkstemp(dir=directory, prefix=prefix)
    os.fchmod(descriptor, 0o600)
    return descriptor, name


def harden_private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == "nt":
        _windows.harden_windows_path(path, directory=True)
    else:
        path.chmod(0o700)


def harden_private_file(path: Path) -> None:
    if os.name == "nt":
        _windows.harden_windows_path(path, directory=False)
    else:
        path.chmod(0o600)
