"""Race-resistant regular-file opening within the document workspace jail."""

from __future__ import annotations

import errno
import os
import stat
from pathlib import Path

from . import windows_native
from .errors import DocumentError, DocumentErrorCode
from .path_identity import (
    descriptor_identity,
    directory_identity,
    regular_path_identity,
)


def _error(code: DocumentErrorCode, message: str) -> DocumentError:
    return DocumentError(code, "import", message)


def _jail_relative(
    path: Path, jail: Path, configured_jail: Path | None
) -> tuple[Path, tuple[str, ...]]:
    if not path.is_absolute():
        raise _error(DocumentErrorCode.INVALID_INPUT, "artifact uri must be absolute")
    root: Path
    if configured_jail is not None and path.is_relative_to(configured_jail):
        root = configured_jail
    elif path.is_relative_to(jail):
        root = jail
    else:
        raise _error(DocumentErrorCode.PERMISSION_DENIED, "artifact escapes the configured home")
    relative = path.relative_to(root)
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise _error(DocumentErrorCode.INVALID_INPUT, "artifact path is unavailable")
    return root, relative.parts


def _open_regular_windows(
    path: Path, jail: Path, configured_jail: Path | None
) -> int:
    root, parts = _jail_relative(path, jail, configured_jail)
    if root != jail:
        raise _error(
            DocumentErrorCode.PERMISSION_DENIED,
            "configured home aliases are unavailable on Windows",
        )
    native = windows_native.api()
    directory_handles: list[tuple[Path, int]] = []
    file_handle = -1
    descriptor = -1
    try:
        root_handle = windows_native.open_handle(
            jail,
            directory=True,
            access=native.FILE_READ_ATTRIBUTES,
            share=native.FILE_SHARE_READ | native.FILE_SHARE_WRITE,
        )
        directory_handles.append((jail, root_handle))
        if windows_native.handle_identity(root_handle) != directory_identity(jail):
            raise _error(DocumentErrorCode.PERMISSION_DENIED, "configured home identity changed")
        current = jail
        for component in parts[:-1]:
            current /= component
            directory_handles.append(
                (
                    current,
                    windows_native.open_handle(
                        current,
                        directory=True,
                        access=native.FILE_READ_ATTRIBUTES,
                        share=native.FILE_SHARE_READ | native.FILE_SHARE_WRITE,
                    ),
                )
            )
        current /= parts[-1]
        file_handle = windows_native.open_handle(
            current,
            directory=False,
            access=native.GENERIC_READ,
            share=native.FILE_SHARE_READ,
        )
        descriptor = windows_native.descriptor(file_handle)
        file_handle = -1
        if descriptor_identity(descriptor) != regular_path_identity(current):
            raise _error(DocumentErrorCode.INVALID_INPUT, "artifact is not a stable regular file")
        for opened_path, handle in directory_handles:
            if windows_native.handle_identity(handle) != directory_identity(opened_path):
                raise _error(DocumentErrorCode.PERMISSION_DENIED, "artifact path identity changed")
        result = descriptor
        descriptor = -1
        return result
    except DocumentError:
        raise
    except OSError as exc:
        denied = {
            getattr(errno, "ELOOP", errno.EACCES),
            errno.EACCES,
            errno.EPERM,
            errno.ENOTDIR,
        }
        code = (
            DocumentErrorCode.PERMISSION_DENIED
            if exc.errno in denied
            else DocumentErrorCode.INVALID_INPUT
        )
        raise _error(code, "artifact is not a readable regular file") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if file_handle >= 0:
            windows_native.close_handle(file_handle)
        for _, handle in reversed(directory_handles):
            windows_native.close_handle(handle)


def _open_regular_posix(
    path: Path, jail: Path, configured_jail: Path | None
) -> int:
    root, parts = _jail_relative(path, jail, configured_jail)
    directory_flags = (
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    )
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_fd = -1
    descriptor = -1
    try:
        directory_fd = os.open(root, directory_flags)
        root_opened = os.fstat(directory_fd)
        jail_metadata = jail.stat(follow_symlinks=False)
        if (root_opened.st_dev, root_opened.st_ino) != (
            jail_metadata.st_dev,
            jail_metadata.st_ino,
        ):
            raise _error(DocumentErrorCode.PERMISSION_DENIED, "configured home identity changed")
        for component in parts[:-1]:
            next_fd = os.open(component, directory_flags | nofollow, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        descriptor = os.open(
            parts[-1],
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NONBLOCK", 0)
            | nofollow,
            dir_fd=directory_fd,
        )
        opened = os.fstat(descriptor)
        current = os.stat(parts[-1], dir_fd=directory_fd, follow_symlinks=False)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            current.st_dev,
            current.st_ino,
        ):
            raise _error(DocumentErrorCode.INVALID_INPUT, "artifact is not a stable regular file")
        result = descriptor
        descriptor = -1
        return result
    except DocumentError:
        raise
    except OSError as exc:
        denied = {errno.ELOOP, errno.EACCES, errno.EPERM, errno.ENOTDIR}
        code = (
            DocumentErrorCode.PERMISSION_DENIED
            if exc.errno in denied
            else DocumentErrorCode.INVALID_INPUT
        )
        raise _error(code, "artifact is not a readable regular file") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if directory_fd >= 0:
            os.close(directory_fd)


def open_regular(path: Path, jail: Path, configured_jail: Path | None = None) -> int:
    """Open each component without following aliases and hold it against races."""
    if os.name == "nt":
        return _open_regular_windows(path, jail, configured_jail)
    return _open_regular_posix(path, jail, configured_jail)
