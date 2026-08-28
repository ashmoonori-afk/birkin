"""Linux independent-inode no-replace publication."""

from __future__ import annotations

import errno
import os
from pathlib import Path

from .export_descriptor_copy import copy_descriptor
from .export_named_publish import publish_named_copy

_CAPABILITY_ERRORS = frozenset({
    errno.EINVAL,
    errno.ENOENT,
    errno.ENOSYS,
    errno.ENOTSUP,
    getattr(errno, "EOPNOTSUPP", errno.ENOTSUP),
    errno.EPERM,
    errno.EXDEV,
})


def publish_linux_copy(
    source_descriptor: int,
    destination: Path,
) -> None:
    temporary_flag = getattr(os, "O_TMPFILE", 0)
    if temporary_flag == 0:
        publish_named_copy(source_descriptor, destination)
        return
    try:
        temporary = os.open(
            destination.parent,
            os.O_RDWR
            | temporary_flag
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        try:
            copy_descriptor(source_descriptor, temporary)
            os.fsync(temporary)
            _link_anonymous(temporary, destination)
        finally:
            os.close(temporary)
    except OSError as exc:
        if exc.errno not in _CAPABILITY_ERRORS:
            raise
        publish_named_copy(source_descriptor, destination)


def _link_anonymous(descriptor: int, destination: Path) -> None:
    descriptor_path = Path(f"/proc/self/fd/{descriptor}")
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
