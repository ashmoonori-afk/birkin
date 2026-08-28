"""Handle-bound Windows directory and file DACL hardening."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

from birkin.private_storage_windows import current_windows_owner_sid
from birkin.private_storage_windows_handle import (
    CtypesWindowsFileApi,
    FILE_ATTRIBUTE_DIRECTORY,
    FILE_ATTRIBUTE_REPARSE_POINT,
    FILE_FLAG_OPEN_REPARSE_POINT,
    FILE_SHARE_DELETE,
    FILE_SHARE_READ,
    FILE_SHARE_WRITE,
    FILE_TYPE_DISK,
    OPEN_EXISTING,
    READ_CONTROL,
    WRITE_DAC,
    WRITE_OWNER,
    WindowsFileApi,
)

_FILE_FLAG_BACKUP_SEMANTICS: Final = 0x02000000


def _harden_windows_path(
    path: Path,
    *,
    directory: bool,
    api: WindowsFileApi,
) -> None:
    for parent in reversed(path.absolute().parents):
        _validate_windows_directory(parent, api)
    flags = FILE_FLAG_OPEN_REPARSE_POINT
    if directory:
        flags |= _FILE_FLAG_BACKUP_SEMANTICS
    handle = api.create_file(
        path,
        desired_access=READ_CONTROL | WRITE_DAC | WRITE_OWNER,
        share_mode=(
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE
        ),
        creation_disposition=OPEN_EXISTING,
        flags_and_attributes=flags,
    )
    try:
        _validate_windows_path_kind(handle, directory=directory, api=api)
        api.set_owner_only_dacl(handle, directory=directory)
    finally:
        api.close_handle(handle)


def _validate_windows_directory(
    path: Path,
    api: WindowsFileApi,
) -> None:
    handle = api.create_file(
        path,
        desired_access=READ_CONTROL,
        share_mode=(
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE
        ),
        creation_disposition=OPEN_EXISTING,
        flags_and_attributes=(
            FILE_FLAG_OPEN_REPARSE_POINT | _FILE_FLAG_BACKUP_SEMANTICS
        ),
    )
    try:
        _validate_windows_path_kind(handle, directory=True, api=api)
    finally:
        api.close_handle(handle)


def _validate_windows_path_kind(
    handle: int,
    *,
    directory: bool,
    api: WindowsFileApi,
) -> None:
    if api.get_file_type(handle) != FILE_TYPE_DISK:
        raise OSError("private storage path is not a disk path")
    attributes = api.get_file_attributes(handle)
    if attributes & FILE_ATTRIBUTE_REPARSE_POINT:
        raise OSError("private storage path is a reparse point")
    if bool(attributes & FILE_ATTRIBUTE_DIRECTORY) != directory:
        raise OSError("private storage path kind changed")


def harden_windows_path_by_handle(path: Path, *, directory: bool) -> None:
    system_root = os.environ.get("SystemRoot")
    if not system_root:
        raise OSError("cannot locate Windows security tools")
    api = CtypesWindowsFileApi(current_windows_owner_sid(system_root))
    _harden_windows_path(path, directory=directory, api=api)
