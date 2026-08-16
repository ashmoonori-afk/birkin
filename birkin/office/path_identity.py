"""Stable native identities and guards for workspace filesystem paths."""

from __future__ import annotations

import errno
import os
import stat
from pathlib import Path

from . import windows_native
from .errors import DocumentError, DocumentErrorCode


def _error(message: str) -> DocumentError:
    return DocumentError(DocumentErrorCode.PERMISSION_DENIED, "import", message)


def descriptor_identity(descriptor: int) -> tuple[int, int]:
    if os.name == "nt":
        return windows_native.descriptor_identity(descriptor)
    metadata = os.fstat(descriptor)
    return metadata.st_dev, metadata.st_ino


def guard_identity(handle: int) -> tuple[int, int]:
    if os.name == "nt":
        return windows_native.handle_identity(handle)
    metadata = os.fstat(handle)
    return metadata.st_dev, metadata.st_ino


def close_guard(handle: int) -> None:
    if os.name == "nt":
        windows_native.close_handle(handle)
    else:
        os.close(handle)


def open_directory_guard(path: Path, expected: tuple[int, int]) -> int:
    """Hold the exact directory open and deny replacement while publishing."""
    if os.name == "nt":
        native = windows_native.api()
        handle = windows_native.open_handle(
            path,
            directory=True,
            access=native.FILE_READ_ATTRIBUTES,
            share=native.FILE_SHARE_READ | native.FILE_SHARE_WRITE,
        )
    else:
        flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        handle = os.open(path, flags)
    if guard_identity(handle) != expected:
        close_guard(handle)
        raise _error("workspace directory identity changed")
    return handle


def open_identity_guard(path: Path, expected: tuple[int, int]) -> int:
    """Hold a regular pathname and require one exact native identity."""
    if os.name == "nt":
        native = windows_native.api()
        handle = windows_native.open_handle(
            path,
            directory=False,
            access=native.FILE_READ_ATTRIBUTES,
            share=native.FILE_SHARE_READ | native.FILE_SHARE_WRITE,
        )
    else:
        handle = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
    if guard_identity(handle) != expected:
        close_guard(handle)
        raise DocumentError(
            DocumentErrorCode.PERMISSION_DENIED,
            "emit",
            "temporary file identity changed",
        )
    return handle


def open_regular_guard(path: Path, descriptor: int) -> int:
    """Hold a pathname on the same regular file as an existing descriptor."""
    return open_identity_guard(path, descriptor_identity(descriptor))


def regular_path_identity(path: Path) -> tuple[int, int]:
    if os.name == "nt":
        native = windows_native.api()
        handle = windows_native.open_handle(
            path,
            directory=False,
            access=native.FILE_READ_ATTRIBUTES,
            share=native.FILE_SHARE_READ | native.FILE_SHARE_WRITE | native.FILE_SHARE_DELETE,
        )
        try:
            return windows_native.handle_identity(handle)
        finally:
            windows_native.close_handle(handle)
    metadata = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(metadata.st_mode):
        raise OSError(errno.EINVAL, "path is not a regular file")
    return metadata.st_dev, metadata.st_ino


def directory_identity(path: Path) -> tuple[int, int]:
    try:
        if os.name == "nt":
            native = windows_native.api()
            handle = windows_native.open_handle(
                path,
                directory=True,
                access=native.FILE_READ_ATTRIBUTES,
                share=native.FILE_SHARE_READ | native.FILE_SHARE_WRITE | native.FILE_SHARE_DELETE,
            )
            try:
                return windows_native.handle_identity(handle)
            finally:
                windows_native.close_handle(handle)
        metadata = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise _error("workspace directory is unavailable") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise _error("workspace directory is not a directory")
    return metadata.st_dev, metadata.st_ino


def ensure_directory_identity(path: Path, expected: tuple[int, int]) -> None:
    if directory_identity(path) != expected:
        raise _error("workspace directory identity changed")


def sync_directory(
    path: Path,
    expected: tuple[int, int],
    *,
    platform: str | None = None,
) -> None:
    """Durably sync POSIX directory metadata; Windows publication flushes file handles."""
    ensure_directory_identity(path, expected)
    if (os.name if platform is None else platform) == "nt":
        return
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        if descriptor_identity(descriptor) != expected:
            raise _error("workspace directory identity changed")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def ensure_open_identity(descriptor: int, name: str, directory_fd: int) -> None:
    try:
        current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        opened = os.fstat(descriptor)
    except OSError as exc:
        raise DocumentError(
            DocumentErrorCode.PERMISSION_DENIED, "emit", "temporary file identity changed"
        ) from exc
    if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
        raise DocumentError(
            DocumentErrorCode.PERMISSION_DENIED, "emit", "temporary file identity changed"
        )


def ensure_path_identity(descriptor: int, path: Path) -> None:
    try:
        current = regular_path_identity(path)
        opened = descriptor_identity(descriptor)
    except OSError as exc:
        raise DocumentError(
            DocumentErrorCode.PERMISSION_DENIED, "emit", "temporary file identity changed"
        ) from exc
    if current != opened:
        raise DocumentError(
            DocumentErrorCode.PERMISSION_DENIED, "emit", "temporary file identity changed"
        )
