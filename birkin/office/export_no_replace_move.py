"""Cross-platform no-replace rename for one helper pathname."""

from __future__ import annotations

import ctypes
import errno
import os
import sys
from pathlib import Path
from typing import cast

_RENAME_NOREPLACE = 1
_RENAME_EXCHANGE = 2
_RENAME_EXCL = 4
_RENAME_SWAP = 2


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


def move_no_replace_between(
    source_directory: int,
    source_name: str,
    destination_directory: int,
    destination_name: str,
) -> None:
    match sys.platform:
        case "darwin":
            _rename_darwin_between(
                source_directory,
                source_name,
                destination_directory,
                destination_name,
            )
        case platform if platform.startswith("linux"):
            _rename_linux_between(
                source_directory,
                source_name,
                destination_directory,
                destination_name,
            )
        case _:
            raise OSError(
                errno.ENOTSUP,
                "descriptor-relative no-replace moves are unavailable",
                destination_name,
            )


def exchange_between(
    directory: int,
    first_name: str,
    second_name: str,
) -> None:
    match sys.platform:
        case "darwin":
            _rename_darwin_between(
                directory,
                first_name,
                directory,
                second_name,
                flags=_RENAME_SWAP,
            )
        case platform if platform.startswith("linux"):
            _rename_linux_between(
                directory,
                first_name,
                directory,
                second_name,
                flags=_RENAME_EXCHANGE,
            )
        case _:
            raise OSError(
                errno.ENOTSUP,
                "atomic path exchange is unavailable",
                second_name,
            )


def _rename_darwin(source: Path, destination: Path) -> None:
    directory = _directory_descriptor(source.parent)
    try:
        _rename_darwin_between(
            directory,
            source.name,
            directory,
            destination.name,
        )
    finally:
        os.close(directory)


def _rename_darwin_between(
    source_directory: int,
    source_name: str,
    destination_directory: int,
    destination_name: str,
    *,
    flags: int = _RENAME_EXCL,
) -> None:
    rename = ctypes.CDLL(None, use_errno=True).renameatx_np
    rename.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    rename.restype = ctypes.c_int
    result = cast(
        "int",
        rename(
            source_directory,
            os.fsencode(source_name),
            destination_directory,
            os.fsencode(destination_name),
            flags,
        ),
    )
    _raise_rename_error(result, Path(destination_name))


def _rename_linux(source: Path, destination: Path) -> None:
    directory = _directory_descriptor(source.parent)
    try:
        _rename_linux_between(
            directory,
            source.name,
            directory,
            destination.name,
        )
    finally:
        os.close(directory)


def _rename_linux_between(
    source_directory: int,
    source_name: str,
    destination_directory: int,
    destination_name: str,
    *,
    flags: int = _RENAME_NOREPLACE,
) -> None:
    rename = ctypes.CDLL(None, use_errno=True).renameat2
    rename.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    rename.restype = ctypes.c_int
    result = cast(
        "int",
        rename(
            source_directory,
            os.fsencode(source_name),
            destination_directory,
            os.fsencode(destination_name),
            flags,
        ),
    )
    _raise_rename_error(result, Path(destination_name))


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
