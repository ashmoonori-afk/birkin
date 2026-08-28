"""No-replace export publication from an already validated descriptor."""

from __future__ import annotations

import ctypes
import errno
import os
import sys
from pathlib import Path

from .export_io import regular_file_identity
from .export_named_publish import publish_named_copy

_CAPABILITY_ERRORS = frozenset({
    errno.EINVAL,
    errno.ENOSYS,
    errno.ENOTSUP,
    getattr(errno, "EOPNOTSUPP", errno.ENOTSUP),
    errno.EXDEV,
})


def publish_open_file(
    source_descriptor: int,
    destination: Path,
) -> tuple[int, int]:
    match sys.platform:
        case "darwin":
            try:
                _clone_darwin(source_descriptor, destination)
            except OSError as exc:
                if exc.errno not in _CAPABILITY_ERRORS:
                    raise
                publish_named_copy(source_descriptor, destination)
        case "win32":
            from .export_inode_publish_windows import publish_windows_handle

            publish_windows_handle(source_descriptor, destination)
        case platform if platform.startswith("linux"):
            from .export_inode_publish_linux import publish_linux_copy

            publish_linux_copy(source_descriptor, destination)
        case _:
            link_descriptor(source_descriptor, destination)
    return regular_file_identity(destination)


def _clone_darwin(source_descriptor: int, destination: Path) -> None:
    clone = ctypes.CDLL(None, use_errno=True).fclonefileat
    clone.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
    ]
    clone.restype = ctypes.c_int
    directory = os.open(
        destination.parent,
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        if clone(
            source_descriptor,
            directory,
            os.fsencode(destination.name),
            0,
        ) != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), destination)
    finally:
        os.close(directory)


def link_descriptor(source_descriptor: int, destination: Path) -> None:
    descriptor_path = Path(f"/proc/self/fd/{source_descriptor}")
    if not descriptor_path.exists():
        descriptor_path = Path(f"/dev/fd/{source_descriptor}")
    if not descriptor_path.exists():
        raise OSError(
            errno.ENOTSUP,
            "descriptor-based hard links are unavailable",
            destination,
        )
    directory = os.open(
        destination.parent,
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.link(
            descriptor_path,
            destination.name,
            dst_dir_fd=directory,
            follow_symlinks=True,
        )
    finally:
        os.close(directory)
