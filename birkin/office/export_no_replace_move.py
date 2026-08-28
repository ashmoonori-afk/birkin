"""Cross-platform no-replace rename for one helper pathname."""

from __future__ import annotations

import ctypes
import errno
import os
import sys
from pathlib import Path
from typing import cast

_RENAME_NOREPLACE = 1
_RENAME_EXCL = 4


def move_no_replace(source: Path, destination: Path) -> None:
    match sys.platform:
        case "darwin":
            _rename_darwin(source, destination)
        case "win32":
            from .export_inode_publish_windows import (
                move_windows_path_no_replace,
            )

            move_windows_path_no_replace(source, destination)
        case platform if platform.startswith("linux"):
            _rename_linux(source, destination)
        case _:
            raise OSError(
                errno.ENOTSUP,
                "no-replace helper moves are unavailable",
                destination,
            )


def _rename_darwin(source: Path, destination: Path) -> None:
    rename = ctypes.CDLL(None, use_errno=True).renameatx_np
    rename.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    rename.restype = ctypes.c_int
    directory = _directory_descriptor(source.parent)
    try:
        result = cast(
            "int",
            rename(
                directory,
                os.fsencode(source.name),
                directory,
                os.fsencode(destination.name),
                _RENAME_EXCL,
            ),
        )
        _raise_rename_error(result, destination)
    finally:
        os.close(directory)


def _rename_linux(source: Path, destination: Path) -> None:
    rename = ctypes.CDLL(None, use_errno=True).renameat2
    rename.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    rename.restype = ctypes.c_int
    directory = _directory_descriptor(source.parent)
    try:
        result = cast(
            "int",
            rename(
                directory,
                os.fsencode(source.name),
                directory,
                os.fsencode(destination.name),
                _RENAME_NOREPLACE,
            ),
        )
        _raise_rename_error(result, destination)
    finally:
        os.close(directory)


def _directory_descriptor(path: Path) -> int:
    return os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )


def _raise_rename_error(result: int, destination: Path) -> None:
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), destination)
