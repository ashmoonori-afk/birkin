"""Cross-platform no-follow descriptors with Windows delete sharing."""

from __future__ import annotations

import os
from pathlib import Path

from . import windows_native

_GENERIC_WRITE = 0x40000000


def open_export_descriptor(path: Path, *, writable: bool) -> int:
    if os.name != "nt":
        return os.open(
            path,
            (os.O_RDWR if writable else os.O_RDONLY)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_BINARY", 0),
        )
    import msvcrt

    native = windows_native.api()
    handle = windows_native.open_handle(
        path,
        directory=False,
        access=(
            native.GENERIC_READ
            | (_GENERIC_WRITE if writable else 0)
        ),
        share=(
            native.FILE_SHARE_READ
            | native.FILE_SHARE_WRITE
            | native.FILE_SHARE_DELETE
        ),
    )
    try:
        return msvcrt.open_osfhandle(
            handle,
            (os.O_RDWR if writable else os.O_RDONLY)
            | getattr(os, "O_BINARY", 0),
        )
    except OSError:
        windows_native.close_handle(handle)
        raise
