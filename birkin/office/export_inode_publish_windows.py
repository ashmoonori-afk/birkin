"""Windows independent-inode handle-bound publication."""

from __future__ import annotations

import ctypes
import os
import secrets
from ctypes import wintypes
from pathlib import Path
from typing import cast, final

from . import windows_native
from .export_descriptor_copy import copy_descriptor
from .export_quarantine_retire import retire_windows_descriptor

_DELETE = 0x00010000
_GENERIC_WRITE = 0x40000000
_CREATE_NEW = 1
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_FILE_RENAME_INFORMATION = 10


@final
class _IoStatusBlock(ctypes.Structure):
    _fields_ = [
        ("status", ctypes.c_void_p),
        ("information", ctypes.c_void_p),
    ]


@final
class _FileNameHeader(ctypes.Structure):
    _fields_ = [
        ("replace_if_exists", ctypes.c_ubyte),
        ("root_directory", wintypes.HANDLE),
        ("file_name_length", wintypes.ULONG),
        ("file_name", wintypes.WCHAR * 1),
    ]


def publish_windows_handle(
    source_descriptor: int,
    destination: Path,
) -> None:
    temporary, _ = _create_temporary(destination)
    published = False
    try:
        copy_descriptor(source_descriptor, temporary)
        os.fsync(temporary)
        _rename_handle(temporary, destination)
        published = True
    finally:
        if not published:
            os.ftruncate(temporary, 0)
            os.fsync(temporary)
            try:
                retire_windows_descriptor(temporary)
            except OSError:
                pass
        os.close(temporary)


def _create_temporary(destination: Path) -> tuple[int, Path]:
    import msvcrt

    native = windows_native.api()
    path = destination.with_name(
        f".birkin-publish-{secrets.token_hex(16)}.tmp"
    )
    raw_handle = cast(
        "int | None",
        native.create_file(
            windows_native.windows_path(path),
            native.GENERIC_READ | _GENERIC_WRITE | _DELETE,
            (
                native.FILE_SHARE_READ
                | native.FILE_SHARE_WRITE
                | native.FILE_SHARE_DELETE
            ),
            None,
            _CREATE_NEW,
            _FILE_ATTRIBUTE_NORMAL,
            None,
        ),
    )
    if raw_handle is None or raw_handle == native.invalid_handle:
        raise native.ctypes.WinError(native.ctypes.get_last_error())
    try:
        return (
            msvcrt.open_osfhandle(
                raw_handle,
                os.O_RDWR | getattr(os, "O_BINARY", 0),
            ),
            path,
        )
    except OSError:
        windows_native.close_handle(raw_handle)
        raise


def _rename_handle(descriptor: int, destination: Path) -> None:
    import msvcrt

    _rename_raw_handle(
        msvcrt.get_osfhandle(descriptor),
        destination,
    )


def move_windows_descriptor_no_replace(
    descriptor: int,
    destination: Path,
) -> None:
    _rename_handle(descriptor, destination)


def move_windows_path_no_replace(
    source: Path,
    destination: Path,
) -> None:
    native = windows_native.api()
    handle = windows_native.open_handle(
        source,
        directory=False,
        access=native.GENERIC_READ | _DELETE,
        share=(
            native.FILE_SHARE_READ
            | native.FILE_SHARE_WRITE
            | native.FILE_SHARE_DELETE
        ),
    )
    try:
        _rename_raw_handle(handle, destination)
    finally:
        windows_native.close_handle(handle)


def _rename_raw_handle(handle: int, destination: Path) -> None:
    native = windows_native.api()
    directory = windows_native.open_handle(
        destination.parent,
        directory=True,
        access=native.FILE_READ_ATTRIBUTES,
        share=(
            native.FILE_SHARE_READ
            | native.FILE_SHARE_WRITE
            | native.FILE_SHARE_DELETE
        ),
    )
    try:
        information = _name_information(directory, destination.name)
        io_status = _IoStatusBlock()
        set_information = ctypes.WinDLL(
            "ntdll",
        ).NtSetInformationFile
        set_information.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_IoStatusBlock),
            ctypes.c_void_p,
            wintypes.ULONG,
            wintypes.ULONG,
        ]
        set_information.restype = ctypes.c_int32
        status = cast(
            "int",
            set_information(
                handle,
                ctypes.byref(io_status),
                information,
                len(information),
                _FILE_RENAME_INFORMATION,
            ),
        )
        if status < 0:
            raise _windows_status_error(status)
    finally:
        windows_native.close_handle(directory)


def _name_information(
    directory: int,
    name: str,
) -> ctypes.Array[ctypes.c_char]:
    encoded = name.encode("utf-16-le")
    size = _FileNameHeader.file_name.offset + len(encoded) + 2
    information = ctypes.create_string_buffer(size)
    header = _FileNameHeader.from_buffer(information)
    header.replace_if_exists = 0
    header.root_directory = directory
    header.file_name_length = len(encoded)
    _ = ctypes.memmove(
        ctypes.addressof(information) + _FileNameHeader.file_name.offset,
        encoded,
        len(encoded),
    )
    return information


def _windows_status_error(status: int) -> OSError:
    convert = ctypes.WinDLL("ntdll").RtlNtStatusToDosError
    convert.argtypes = [ctypes.c_int32]
    convert.restype = wintypes.ULONG
    return ctypes.WinError(cast("int", convert(status)))
