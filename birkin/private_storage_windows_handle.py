"""Handle-bound Windows private-file opening."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path
from typing import Final, Protocol, final

from birkin.private_storage_windows import (
    _current_windows_owner_sid,
    _owner_only_security_parts,
)

_GENERIC_READ: Final = 0x80000000
_READ_CONTROL: Final = 0x00020000
_WRITE_DAC: Final = 0x00040000
_WRITE_OWNER: Final = 0x00080000
_FILE_SHARE_READ: Final = 0x00000001
_FILE_SHARE_WRITE: Final = 0x00000002
_FILE_SHARE_DELETE: Final = 0x00000004
_OPEN_EXISTING: Final = 3
_FILE_ATTRIBUTE_DIRECTORY: Final = 0x00000010
_FILE_ATTRIBUTE_NORMAL: Final = 0x00000080
_FILE_ATTRIBUTE_REPARSE_POINT: Final = 0x00000400
_FILE_FLAG_OPEN_REPARSE_POINT: Final = 0x00200000
_FILE_TYPE_DISK: Final = 1
_FILE_ATTRIBUTE_TAG_INFO_CLASS: Final = 9
_SE_FILE_OBJECT: Final = 1
_OWNER_SECURITY_INFORMATION: Final = 0x00000001
_DACL_SECURITY_INFORMATION: Final = 0x00000004
_PROTECTED_DACL_SECURITY_INFORMATION: Final = 0x80000000


class _WindowsFileApi(Protocol):
    def create_file(
        self,
        path: Path,
        *,
        desired_access: int,
        share_mode: int,
        creation_disposition: int,
        flags_and_attributes: int,
    ) -> int: ...

    def get_file_type(self, handle: int) -> int: ...

    def get_file_attributes(self, handle: int) -> int: ...

    def set_owner_only_dacl(
        self,
        handle: int,
        *,
        directory: bool,
    ) -> None: ...

    def open_osfhandle(self, handle: int) -> int: ...

    def close_handle(self, handle: int) -> None: ...


@final
class _FileAttributeTagInfo(ctypes.Structure):
    _fields_ = [
        ("file_attributes", wintypes.DWORD),
        ("reparse_tag", wintypes.DWORD),
    ]


@final
class _CtypesWindowsFileApi:
    def __init__(self, sid: str) -> None:
        self._sid = sid

    def create_file(
        self,
        path: Path,
        *,
        desired_access: int,
        share_mode: int,
        creation_disposition: int,
        flags_and_attributes: int,
    ) -> int:
        create_file = ctypes.windll.kernel32.CreateFileW
        create_file.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        create_file.restype = wintypes.HANDLE
        raw_handle = create_file(
            str(path),
            desired_access,
            share_mode,
            None,
            creation_disposition,
            flags_and_attributes,
            None,
        )
        if not isinstance(raw_handle, int):
            raise OSError("Windows did not return a file handle")
        if raw_handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError()
        return raw_handle

    def get_file_type(self, handle: int) -> int:
        get_file_type = ctypes.windll.kernel32.GetFileType
        get_file_type.argtypes = [wintypes.HANDLE]
        get_file_type.restype = wintypes.DWORD
        file_type = get_file_type(handle)
        if file_type == 0:
            raise ctypes.WinError()
        return file_type

    def get_file_attributes(self, handle: int) -> int:
        information = _FileAttributeTagInfo()
        get_information = (
            ctypes.windll.kernel32.GetFileInformationByHandleEx
        )
        get_information.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        get_information.restype = wintypes.BOOL
        if not get_information(
            handle,
            _FILE_ATTRIBUTE_TAG_INFO_CLASS,
            ctypes.byref(information),
            ctypes.sizeof(information),
        ):
            raise ctypes.WinError()
        return information.file_attributes

    def set_owner_only_dacl(
        self,
        handle: int,
        *,
        directory: bool,
    ) -> None:
        with _owner_only_security_parts(
            self._sid,
            directory=directory,
        ) as security:
            owner, dacl = security
            set_info = ctypes.windll.advapi32.SetSecurityInfo
            set_info.argtypes = [
                wintypes.HANDLE,
                wintypes.DWORD,
                wintypes.DWORD,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_void_p,
            ]
            set_info.restype = wintypes.DWORD
            result = set_info(
                handle,
                _SE_FILE_OBJECT,
                _OWNER_SECURITY_INFORMATION
                | _DACL_SECURITY_INFORMATION
                | _PROTECTED_DACL_SECURITY_INFORMATION,
                owner,
                None,
                dacl,
                None,
            )
            if result != 0:
                raise ctypes.WinError(result)

    def open_osfhandle(self, handle: int) -> int:
        import msvcrt

        return msvcrt.open_osfhandle(handle, os.O_RDONLY)

    def close_handle(self, handle: int) -> None:
        close_handle = ctypes.windll.kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL
        if not close_handle(handle):
            raise ctypes.WinError()


FILE_ATTRIBUTE_DIRECTORY = _FILE_ATTRIBUTE_DIRECTORY
FILE_ATTRIBUTE_REPARSE_POINT = _FILE_ATTRIBUTE_REPARSE_POINT
FILE_FLAG_OPEN_REPARSE_POINT = _FILE_FLAG_OPEN_REPARSE_POINT
FILE_SHARE_DELETE = _FILE_SHARE_DELETE
FILE_SHARE_READ = _FILE_SHARE_READ
FILE_SHARE_WRITE = _FILE_SHARE_WRITE
FILE_TYPE_DISK = _FILE_TYPE_DISK
OPEN_EXISTING = _OPEN_EXISTING
READ_CONTROL = _READ_CONTROL
WRITE_DAC = _WRITE_DAC
WRITE_OWNER = _WRITE_OWNER
WindowsFileApi = _WindowsFileApi
CtypesWindowsFileApi = _CtypesWindowsFileApi


def _open_windows_private_file(
    path: Path,
    api: _WindowsFileApi,
) -> int:
    handle = api.create_file(
        path,
        desired_access=(
            _GENERIC_READ | _READ_CONTROL | _WRITE_DAC | _WRITE_OWNER
        ),
        share_mode=(
            _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE
        ),
        creation_disposition=_OPEN_EXISTING,
        flags_and_attributes=(
            _FILE_ATTRIBUTE_NORMAL | _FILE_FLAG_OPEN_REPARSE_POINT
        ),
    )
    transferred = False
    try:
        if api.get_file_type(handle) != _FILE_TYPE_DISK:
            raise OSError("private storage path is not a regular file")
        attributes = api.get_file_attributes(handle)
        if attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
            raise OSError("private storage path is a reparse point")
        if attributes & _FILE_ATTRIBUTE_DIRECTORY:
            raise OSError("private storage path is not a regular file")
        api.set_owner_only_dacl(handle, directory=False)
        descriptor = api.open_osfhandle(handle)
        transferred = True
        return descriptor
    finally:
        if not transferred:
            api.close_handle(handle)


def open_windows_private_file(path: Path) -> int:
    system_root = os.environ.get("SystemRoot")
    if not system_root:
        raise OSError("cannot locate Windows security tools")
    api = _CtypesWindowsFileApi(_current_windows_owner_sid(system_root))
    return _open_windows_private_file(path, api)
