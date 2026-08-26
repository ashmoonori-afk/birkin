"""Cross-platform owner-only storage primitives."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

from birkin import private_storage_windows as _windows
from birkin.private_storage_windows_handle import open_windows_private_file

_windows_owner_sid = _windows.windows_owner_sid

__all__ = [
    "create_private_temp",
    "harden_private_directory",
    "harden_private_file",
    "open_private_file_for_read",
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


def open_private_file_for_read(path: Path) -> int:
    """Open one regular owner-only file and transfer descriptor ownership."""
    if os.name == "nt":
        return open_windows_private_file(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise OSError("private storage path is not a regular file")
        os.fchmod(descriptor, 0o600)
    except OSError:
        os.close(descriptor)
        raise
    return descriptor
