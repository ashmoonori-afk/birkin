"""Lazy Windows ctypes bindings for secure filesystem operations."""

from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import Protocol, cast, final


class HandleInformation(Protocol):
    dwFileAttributes: int
    dwVolumeSerialNumber: int
    nFileIndexHigh: int
    nFileIndexLow: int


@final
class _WindowsApi:
    GENERIC_READ = 0x80000000
    FILE_READ_ATTRIBUTES = 0x0080
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    FILE_SHARE_DELETE = 0x00000004
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_DIRECTORY = 0x00000010
    FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
    FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
    FILE_TYPE_DISK = 0x0001
    WAIT_ABANDONED = 0x00000080
    WAIT_FAILED = 0xFFFFFFFF
    WAIT_INFINITE = 0xFFFFFFFF
    WAIT_OBJECT_0 = 0x00000000

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        @final
        class ByHandleFileInformation(ctypes.Structure):
            _fields_ = [
                ("dwFileAttributes", wintypes.DWORD),
                ("ftCreationTime", wintypes.FILETIME),
                ("ftLastAccessTime", wintypes.FILETIME),
                ("ftLastWriteTime", wintypes.FILETIME),
                ("dwVolumeSerialNumber", wintypes.DWORD),
                ("nFileSizeHigh", wintypes.DWORD),
                ("nFileSizeLow", wintypes.DWORD),
                ("nNumberOfLinks", wintypes.DWORD),
                ("nFileIndexHigh", wintypes.DWORD),
                ("nFileIndexLow", wintypes.DWORD),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.ctypes = ctypes
        self.information_type = ByHandleFileInformation
        self.create_file = kernel32.CreateFileW
        self.create_file.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        self.create_file.restype = wintypes.HANDLE
        self.get_information = kernel32.GetFileInformationByHandle
        self.get_information.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ByHandleFileInformation),
        ]
        self.get_information.restype = wintypes.BOOL
        self.get_file_type = kernel32.GetFileType
        self.get_file_type.argtypes = [wintypes.HANDLE]
        self.get_file_type.restype = wintypes.DWORD
        self.close_handle = kernel32.CloseHandle
        self.close_handle.argtypes = [wintypes.HANDLE]
        self.close_handle.restype = wintypes.BOOL
        self.create_mutex = kernel32.CreateMutexW
        self.create_mutex.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        self.create_mutex.restype = wintypes.HANDLE
        self.wait_for_single_object = kernel32.WaitForSingleObject
        self.wait_for_single_object.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.wait_for_single_object.restype = wintypes.DWORD
        self.release_mutex = kernel32.ReleaseMutex
        self.release_mutex.argtypes = [wintypes.HANDLE]
        self.release_mutex.restype = wintypes.BOOL
        self.invalid_handle = ctypes.c_void_p(-1).value


_api_instance: _WindowsApi | None = None


def api() -> _WindowsApi:
    if os.name != "nt":
        raise RuntimeError("Windows file handles are unavailable")
    global _api_instance
    if _api_instance is None:
        _api_instance = _WindowsApi()
    return _api_instance


def windows_path(path: Path) -> str:
    value = str(path.absolute())
    if value.startswith("\\\\?\\"):
        return value
    if value.startswith("\\\\"):
        return "\\\\?\\UNC\\" + value[2:]
    return "\\\\?\\" + value


def close_handle(handle: int) -> None:
    native = api()
    if not native.close_handle(handle):
        raise native.ctypes.WinError(native.ctypes.get_last_error())


def handle_information(handle: int) -> HandleInformation:
    native = api()
    information = native.information_type()
    if not native.get_information(handle, native.ctypes.byref(information)):
        raise native.ctypes.WinError(native.ctypes.get_last_error())
    return cast("HandleInformation", cast("object", information))


def handle_identity(handle: int) -> tuple[int, int]:
    information = handle_information(handle)
    file_id = (int(information.nFileIndexHigh) << 32) | int(information.nFileIndexLow)
    return int(information.dwVolumeSerialNumber), file_id


def open_handle(path: Path, *, directory: bool, access: int, share: int) -> int:
    native = api()
    flags = native.FILE_FLAG_OPEN_REPARSE_POINT | native.FILE_FLAG_BACKUP_SEMANTICS
    handle = cast(
        "int | None",
        native.create_file(
            windows_path(path), access, share, None, native.OPEN_EXISTING, flags, None
        ),
    )
    if handle is None or handle == native.invalid_handle:
        raise native.ctypes.WinError(native.ctypes.get_last_error())
    opened = handle
    try:
        attributes = int(handle_information(opened).dwFileAttributes)
        if attributes & native.FILE_ATTRIBUTE_REPARSE_POINT:
            raise OSError(getattr(errno, "ELOOP", errno.EACCES), "reparse points are refused")
        is_directory = bool(attributes & native.FILE_ATTRIBUTE_DIRECTORY)
        if directory and not is_directory:
            raise OSError(errno.ENOTDIR, "path is not a directory")
        if not directory and is_directory:
            raise OSError(errno.EISDIR, "path is not a regular file")
        if native.get_file_type(opened) != native.FILE_TYPE_DISK:
            raise OSError(errno.EINVAL, "path is not a disk file")
        return opened
    except BaseException:
        try:
            close_handle(opened)
        except OSError:
            pass
        raise


def open_read_guard(path: Path) -> int:
    """Open a readable file while denying write, delete, and replacement opens."""
    native = api()
    handle = open_handle(
        path,
        directory=False,
        access=native.GENERIC_READ,
        share=native.FILE_SHARE_READ,
    )
    try:
        return descriptor(handle)
    except BaseException:
        close_handle(handle)
        raise


def descriptor_identity(descriptor: int) -> tuple[int, int]:
    import msvcrt

    handle = msvcrt.get_osfhandle(descriptor)
    if handle == -1:
        raise OSError(errno.EBADF, "descriptor is closed")
    return handle_identity(handle)


def descriptor(handle: int) -> int:
    import msvcrt

    return msvcrt.open_osfhandle(handle, os.O_RDONLY | getattr(os, "O_BINARY", 0))


def acquire_publication_mutex(identity: tuple[int, int]) -> int:
    native = api()
    name = f"Local\\BirkinOfficePublication-{identity[0]:x}-{identity[1]:x}"
    handle = cast("int | None", native.create_mutex(None, False, name))
    if not handle:
        raise native.ctypes.WinError(native.ctypes.get_last_error())
    opened = handle
    wait_result = cast("int", native.wait_for_single_object(opened, native.WAIT_INFINITE))
    if wait_result not in {native.WAIT_OBJECT_0, native.WAIT_ABANDONED}:
        try:
            close_handle(opened)
        finally:
            if wait_result == native.WAIT_FAILED:
                raise native.ctypes.WinError(native.ctypes.get_last_error())
            raise OSError(errno.EIO, "publication mutex wait failed")
    return opened


def release_publication_mutex(handle: int) -> None:
    native = api()
    release_error: OSError | None = None
    if not native.release_mutex(handle):
        release_error = native.ctypes.WinError(native.ctypes.get_last_error())
    try:
        close_handle(handle)
    except OSError as exc:
        release_error = release_error or exc
    if release_error is not None:
        raise release_error
