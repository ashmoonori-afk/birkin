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
    "atomic_write_private_text",
    "create_private_temp",
    "harden_private_directory",
    "harden_private_file",
    "harden_private_tree",
    "open_private_file_for_read",
    "publish_private_temp",
    "read_private_text",
]


def _is_reparse(metadata: os.stat_result) -> bool:
    attributes = getattr(metadata, "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _validate_path(path: Path, *, directory: bool) -> os.stat_result:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or _is_reparse(metadata):
        raise OSError(f"private storage path is a symlink or reparse point: {path}")
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(metadata.st_mode):
        kind = "directory" if directory else "regular file"
        raise OSError(f"private storage path is not a {kind}: {path}")
    return metadata


def _validate_parent(path: Path) -> None:
    try:
        _validate_path(path, directory=True)
    except FileNotFoundError:
        pass


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
    _validate_parent(path.parent)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    before = _validate_path(path, directory=True)
    if os.name == "nt":
        _harden_windows_path(path, directory=True)
    else:
        flags = (
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(path, flags)
        try:
            os.fchmod(descriptor, 0o700)
        finally:
            os.close(descriptor)
    after = _validate_path(path, directory=True)
    if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
        raise OSError("private storage directory changed while being secured")


def harden_private_file(path: Path) -> None:
    _validate_parent(path.parent)
    before = _validate_path(path, directory=False)
    if os.name == "nt":
        _harden_windows_path(path, directory=False)
    else:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            os.fchmod(descriptor, 0o600)
        finally:
            os.close(descriptor)
    after = _validate_path(path, directory=False)
    if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
        raise OSError("private storage file changed while being secured")


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
    temporary_before = _validate_path(temporary, directory=False)
    parent_before = _validate_path(destination.parent, directory=True)
    if os.name == "nt":
        published = _windows.publish_windows_private_temp(
            temporary,
            destination,
        )
        if not published:
            return False
    else:
        try:
            os.link(temporary, destination)
        except FileExistsError:
            return False
    destination_after = _validate_path(destination, directory=False)
    parent_after = _validate_path(destination.parent, directory=True)
    if (temporary_before.st_dev, temporary_before.st_ino) != (
        destination_after.st_dev,
        destination_after.st_ino,
    ):
        raise OSError("private temporary file changed while being published")
    if (parent_before.st_dev, parent_before.st_ino) != (
        parent_after.st_dev,
        parent_after.st_ino,
    ):
        raise OSError("private storage directory changed while publishing")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(destination.parent, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return True


def open_private_file_for_read(path: Path) -> int:
    """Open one regular owner-only file and transfer descriptor ownership."""
    _validate_parent(path.parent)
    before = _validate_path(path, directory=False)
    if os.name == "nt":
        descriptor = open_windows_private_file(path)
    else:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise OSError("private storage path is not a regular file")
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        after = _validate_path(path, directory=False)
        identity = (opened.st_dev, opened.st_ino)
        if identity != (before.st_dev, before.st_ino) or identity != (
            after.st_dev,
            after.st_ino,
        ):
            raise OSError("private storage file changed while being opened")
    except OSError:
        os.close(descriptor)
        raise
    return descriptor


def read_private_text(path: Path, *, encoding: str = "utf-8") -> str:
    descriptor = open_private_file_for_read(path)
    with os.fdopen(descriptor, "r", encoding=encoding) as handle:
        return handle.read()


def atomic_write_private_text(
    path: Path,
    text: str,
    *,
    encoding: str = "utf-8",
) -> None:
    harden_private_directory(path.parent)
    try:
        harden_private_file(path)
    except FileNotFoundError:
        pass
    descriptor, temporary_name = create_private_temp(
        path.parent,
        prefix=f".{path.name}.",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        harden_private_directory(path.parent)
        try:
            harden_private_file(path)
        except FileNotFoundError:
            pass
        os.replace(temporary, path)
        harden_private_file(path)
        if os.name != "nt":
            directory = os.open(
                path.parent,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)
