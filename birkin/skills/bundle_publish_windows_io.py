"""Exact-object Windows filesystem operations for bundle publication."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

READ_ATTRIBUTES = 0x0080
GENERIC_WRITE = 0x40000000
DELETE = 0x00010000
SHARE_READ_WRITE = 0x00000001 | 0x00000002
SHARE_READ_WRITE_DELETE = SHARE_READ_WRITE | 0x00000004
OPEN_EXISTING = 3
CREATE_NEW = 1
BACKUP_SEMANTICS = 0x02000000
OPEN_REPARSE_POINT = 0x00200000
REPARSE_ATTRIBUTE = 0x00000400
DIRECTORY_ATTRIBUTE = 0x00000010


def open_handle(
    kernel32: Any,
    path: Path,
    *,
    access: int,
    share: int = SHARE_READ_WRITE,
    disposition: int = OPEN_EXISTING,
    directory: bool = True,
) -> int:
    import ctypes
    from ctypes import wintypes

    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    flags = OPEN_REPARSE_POINT
    if directory:
        flags |= BACKUP_SEMANTICS
    handle = create_file(
        str(path),
        access,
        share,
        None,
        disposition,
        flags,
        None,
    )
    if handle == wintypes.HANDLE(-1).value:
        raise OSError(ctypes.get_last_error(), str(path))
    return int(handle)


def information(kernel32: Any, handle: int) -> tuple[int, int]:
    import ctypes
    from ctypes import wintypes

    class ByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("FileAttributes", wintypes.DWORD),
            ("CreationTime", wintypes.FILETIME),
            ("LastAccessTime", wintypes.FILETIME),
            ("LastWriteTime", wintypes.FILETIME),
            ("VolumeSerialNumber", wintypes.DWORD),
            ("FileSizeHigh", wintypes.DWORD),
            ("FileSizeLow", wintypes.DWORD),
            ("NumberOfLinks", wintypes.DWORD),
            ("FileIndexHigh", wintypes.DWORD),
            ("FileIndexLow", wintypes.DWORD),
        ]

    get_information = kernel32.GetFileInformationByHandle
    get_information.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
    ]
    get_information.restype = wintypes.BOOL
    info = ByHandleFileInformation()
    if not get_information(
        wintypes.HANDLE(handle),
        ctypes.byref(info),
    ):
        raise OSError(ctypes.get_last_error())
    identity = (int(info.FileIndexHigh) << 32) | int(info.FileIndexLow)
    return int(info.FileAttributes), identity


def close(kernel32: Any, handle: int) -> None:
    import ctypes
    from ctypes import wintypes

    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    if not close_handle(wintypes.HANDLE(handle)):
        raise OSError(ctypes.get_last_error() or 1)


def checked_directory(
    kernel32: Any,
    path: Path,
    *,
    access: int,
    share: int = SHARE_READ_WRITE,
) -> int:
    handle = open_handle(
        kernel32,
        path,
        access=access,
        share=share,
    )
    try:
        attributes, _ = information(kernel32, handle)
        if attributes & REPARSE_ATTRIBUTE:
            raise OSError("bundle directory is a reparse point")
    except BaseException:
        close(kernel32, handle)
        raise
    return handle


def rename(
    kernel32: Any,
    source_handle: int,
    parent_handle: int,
    parent_path: Path,
    name: str,
) -> None:
    import ctypes
    from ctypes import wintypes

    class StatusValue(ctypes.Union):
        _fields_ = [
            ("Status", ctypes.c_long),
            ("Pointer", ctypes.c_void_p),
        ]

    class IoStatusBlock(ctypes.Structure):
        _fields_ = [
            ("value", StatusValue),
            ("Information", ctypes.c_size_t),
        ]

    class FileRenameInformation(ctypes.Structure):
        _fields_ = [
            ("ReplaceIfExists", wintypes.BOOLEAN),
            ("RootDirectory", wintypes.HANDLE),
            ("FileNameLength", wintypes.DWORD),
            ("FileName", wintypes.WCHAR * 1),
        ]

    encoded = (name + "\0").encode("utf-16-le")
    offset = FileRenameInformation.FileName.offset
    buffer = ctypes.create_string_buffer(
        ctypes.sizeof(FileRenameInformation) + len(encoded)
    )
    info = FileRenameInformation.from_buffer(buffer)
    info.ReplaceIfExists = False
    info.RootDirectory = wintypes.HANDLE(parent_handle)
    info.FileNameLength = len(name.encode("utf-16-le"))
    ctypes.memmove(
        ctypes.addressof(buffer) + offset,
        encoded,
        len(encoded),
    )
    ntdll = ctypes.WinDLL("ntdll")
    set_information = ntdll.NtSetInformationFile
    set_information.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(IoStatusBlock),
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    set_information.restype = ctypes.c_long
    status_block = IoStatusBlock()
    status = set_information(
        wintypes.HANDLE(source_handle),
        ctypes.byref(status_block),
        buffer,
        len(buffer),
        10,
    )
    if status < 0:
        convert_status = ntdll.RtlNtStatusToDosError
        convert_status.argtypes = [ctypes.c_long]
        convert_status.restype = wintypes.ULONG
        raise OSError(
            int(convert_status(status)) or 1,
            str(parent_path / name),
        )


def mark_delete(kernel32: Any, handle: int) -> None:
    import ctypes
    from ctypes import wintypes

    class FileDispositionInfo(ctypes.Structure):
        _fields_ = [("DeleteFile", wintypes.BOOLEAN)]

    info = FileDispositionInfo(True)
    set_information = kernel32.SetFileInformationByHandle
    set_information.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    set_information.restype = wintypes.BOOL
    if not set_information(
        wintypes.HANDLE(handle),
        4,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        raise OSError(ctypes.get_last_error())


def delete_tree(
    kernel32: Any,
    path: Path,
    handle: int,
) -> None:
    attributes, _ = information(kernel32, handle)
    if (
        attributes & DIRECTORY_ATTRIBUTE
        and not attributes & REPARSE_ATTRIBUTE
    ):
        for entry in os.scandir(path):
            expected_identity = entry.inode()
            child_path = Path(entry.path)
            child = open_handle(
                kernel32,
                child_path,
                access=READ_ATTRIBUTES | DELETE,
                directory=entry.is_dir(follow_symlinks=False),
            )
            try:
                _, identity = information(kernel32, child)
                if identity != expected_identity:
                    raise OSError("bundle cleanup identity changed")
                delete_tree(kernel32, child_path, child)
                child = -1
            finally:
                if child >= 0:
                    close(kernel32, child)
    mark_delete(kernel32, handle)
    close(kernel32, handle)
