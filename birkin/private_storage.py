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
    "harden_private_tree",
    "open_private_file_for_read",
    "publish_private_temp",
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
    if path.is_symlink() or not path.is_dir():
        raise OSError("private storage root must be a real directory")
    if os.name == "nt":
        _harden_windows_path(path, directory=True)
    else:
        path.chmod(0o700)


def harden_private_file(path: Path) -> None:
    if os.name == "nt":
        _harden_windows_path(path, directory=False)
    else:
        path.chmod(0o600)


def harden_private_tree(root: Path) -> None:
    if os.name != "nt":
        return
    for directory, names, files in os.walk(
        root,
        topdown=True,
        followlinks=False,
    ):
        parent = Path(directory)
        for name in names:
            _harden_windows_path(parent / name, directory=True)
        for name in files:
            _harden_windows_path(parent / name, directory=False)


def _harden_windows_path(path: Path, *, directory: bool) -> None:
    from birkin.private_storage_windows_hardening import (
        harden_windows_path_by_handle,
    )

    harden_windows_path_by_handle(path, directory=directory)


def publish_private_temp(
    temporary: Path,
    destination: Path,
) -> bool:
    if os.name == "nt":
        return _windows.publish_windows_private_temp(
            temporary,
            destination,
        )
    try:
        os.link(temporary, destination)
    except FileExistsError:
        return False
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(destination.parent, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return True


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
