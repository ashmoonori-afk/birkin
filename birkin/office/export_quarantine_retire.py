"""Exact-object helper retirement without truncating caller-owned inodes."""

from __future__ import annotations

import errno
import os
from pathlib import Path
import secrets
import stat

from .export_io import recovery_error
from .export_no_replace_move import move_no_replace_between
from .path_identity import descriptor_identity


def retire_bound_path(
    path: Path,
    descriptor: int,
    expected_identity: tuple[int, int],
) -> None:
    if os.name == "nt":
        _retire_windows(descriptor)
        return
    quarantine = path.parent / ".birkin-retire"
    try:
        quarantine.mkdir(mode=0o700, exist_ok=True)
        directory = os.open(
            quarantine,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        parent = os.open(
            path.parent,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as exc:
        raise recovery_error("export helper quarantine is unavailable") from exc
    try:
        directory_metadata = os.fstat(directory)
        if (
            not stat.S_ISDIR(directory_metadata.st_mode)
            or directory_metadata.st_mode
            & (stat.S_IWGRP | stat.S_IWOTH)
        ):
            raise recovery_error("export helper quarantine is unsafe")
        retired_name = f"retired-{secrets.token_hex(16)}"
        move_no_replace_between(
            parent,
            path.name,
            directory,
            retired_name,
        )
        moved = os.stat(
            retired_name,
            dir_fd=directory,
            follow_symlinks=False,
        )
        moved_identity = (moved.st_dev, moved.st_ino)
        if (
            moved_identity != expected_identity
            or descriptor_identity(descriptor) != expected_identity
        ):
            try:
                move_no_replace_between(
                    directory,
                    retired_name,
                    parent,
                    path.name,
                )
            except OSError:
                pass
            raise recovery_error("export helper changed during quarantine")
        os.fsync(directory)
        os.fsync(parent)
    except OSError as exc:
        raise recovery_error("export helper retirement must finish") from exc
    finally:
        os.close(parent)
        os.close(directory)


def _retire_windows(descriptor: int) -> None:
    import ctypes
    import msvcrt

    from birkin.skills.bundle_publish_windows_io import mark_delete

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    try:
        mark_delete(kernel32, msvcrt.get_osfhandle(descriptor))
    except OSError as exc:
        raise OSError(
            errno.EIO,
            "Windows helper disposition failed",
        ) from exc
