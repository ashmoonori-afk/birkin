"""Windows handle helpers for descriptor-bound generic file tools."""

from __future__ import annotations

import os
from pathlib import Path


def open_created(path: Path) -> int:
    from ..office import windows_native

    return _open_file(
        path,
        writable=True,
        disposition=windows_native.api().CREATE_NEW,
    )


def open_existing_deletable(path: Path) -> int:
    return _open_file(path, writable=True, disposition=None)


def open_existing(path: Path, *, writable: bool) -> int:
    return _open_file(path, writable=writable, disposition=None)


def _open_file(
    path: Path,
    *,
    writable: bool,
    disposition: int | None,
) -> int:
    import msvcrt

    from ..office import windows_native

    native = windows_native.api()
    raw_handle = windows_native.open_handle(
        path,
        directory=False,
        access=(
            native.GENERIC_READ
            | (0x40000000 | 0x00010000 if writable else 0)
        ),
        share=(
            native.FILE_SHARE_READ
            | (
                native.FILE_SHARE_WRITE | native.FILE_SHARE_DELETE
                if writable
                else 0
            )
        ),
        disposition=disposition,
    )
    try:
        return msvcrt.open_osfhandle(
            raw_handle,
            (os.O_RDWR if writable else os.O_RDONLY)
            | getattr(os, "O_BINARY", 0),
        )
    except OSError:
        windows_native.close_handle(raw_handle)
        raise


def replace_with_backup(
    target: Path,
    replacement: Path,
    backup: Path,
) -> None:
    import ctypes
    from ctypes import wintypes
    from typing import cast

    from ..office.windows_native import windows_path

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    replace = kernel32.ReplaceFileW
    replace.argtypes = (
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPVOID,
    )
    replace.restype = wintypes.BOOL
    result = cast(
        "int",
        replace(
            windows_path(target),
            windows_path(replacement),
            windows_path(backup),
            0x00000001,
            None,
            None,
        ),
    )
    if result == 0:
        raise ctypes.WinError(ctypes.get_last_error())


def move_open_descriptor_no_replace(
    descriptor: int,
    destination: Path,
) -> None:
    from ..office.export_inode_publish_windows import (
        move_windows_descriptor_no_replace,
    )

    move_windows_descriptor_no_replace(descriptor, destination)


def final_path(descriptor: int) -> Path:
    import msvcrt

    return handle_final_path(msvcrt.get_osfhandle(descriptor))


def handle_final_path(handle: int) -> Path:
    import ctypes
    from ctypes import wintypes
    from typing import cast

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_path = kernel32.GetFinalPathNameByHandleW
    get_path.argtypes = (
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    get_path.restype = wintypes.DWORD
    length = cast("int", get_path(handle, None, 0, 0))
    if length == 0:
        raise OSError(ctypes.get_last_error())
    buffer = ctypes.create_unicode_buffer(length + 1)
    if cast("int", get_path(handle, buffer, len(buffer), 0)) == 0:
        raise OSError(ctypes.get_last_error())
    raw = cast("str", buffer.value)
    if raw.startswith("\\\\?\\UNC\\"):
        raw = "\\\\" + raw[8:]
    elif raw.startswith("\\\\?\\"):
        raw = raw[4:]
    return Path(raw)


def open_directory(path: Path) -> int:
    from ..office import windows_native

    native = windows_native.api()
    return windows_native.open_handle(
        path,
        directory=True,
        access=native.GENERIC_READ,
        share=native.FILE_SHARE_READ,
    )


def close_handle(handle: int) -> None:
    from ..office.windows_native import close_handle as close_native_handle

    close_native_handle(handle)


def mark_delete(descriptor: int) -> None:
    import ctypes
    import msvcrt

    from ..skills.bundle_publish_windows_io import mark_delete as delete_handle

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    delete_handle(kernel32, msvcrt.get_osfhandle(descriptor))
