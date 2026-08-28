"""Windows owner-only ACL and temporary-file primitives."""

from __future__ import annotations

import ctypes
import os
import re
import secrets
import subprocess
from collections.abc import Generator
from contextlib import contextmanager
from ctypes import wintypes
from functools import lru_cache
from pathlib import Path
from typing import final

_WINDOWS_SID = re.compile(rb"S-\d-\d+(?:-\d+)+")
_SDDL_REVISION_1 = 1
_ERROR_FILE_EXISTS = 80
_ERROR_ALREADY_EXISTS = 183
_MOVEFILE_WRITE_THROUGH = 0x00000008


@final
class _SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.DWORD),
        ("security_descriptor", ctypes.c_void_p),
        ("inherit_handle", wintypes.BOOL),
    ]


def windows_owner_sid(output: bytes) -> str:
    raw_sid = output.rsplit(b",", 1)[-1].strip(b'"\r\n ')
    if _WINDOWS_SID.fullmatch(raw_sid) is None:
        raise OSError("cannot identify the Windows Native file owner")
    return raw_sid.decode("ascii")


@lru_cache(maxsize=1)
def _current_windows_owner_sid(system_root: str) -> str:
    whoami = Path(system_root) / "System32/whoami.exe"
    return windows_owner_sid(
        _run([str(whoami), "/user", "/fo", "csv", "/nh"])
    )


current_windows_owner_sid = _current_windows_owner_sid


@contextmanager
def _owner_only_security_descriptor(
    sid: str,
    *,
    directory: bool,
) -> Generator[ctypes.c_void_p]:
    descriptor = ctypes.c_void_p()
    descriptor_size = wintypes.DWORD()
    convert = (
        ctypes.windll.advapi32
        .ConvertStringSecurityDescriptorToSecurityDescriptorW
    )
    convert.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.DWORD),
    ]
    convert.restype = wintypes.BOOL
    inheritance = "OICI" if directory else ""
    sddl = f"O:{sid}D:P(A;{inheritance};FA;;;{sid})"
    if not convert(
        sddl,
        _SDDL_REVISION_1,
        ctypes.byref(descriptor),
        ctypes.byref(descriptor_size),
    ):
        raise ctypes.WinError()
    try:
        yield descriptor
    finally:
        local_free = ctypes.windll.kernel32.LocalFree
        local_free.argtypes = [ctypes.c_void_p]
        local_free.restype = ctypes.c_void_p
        _ = local_free(descriptor)


@contextmanager
def _owner_only_security_parts(
    sid: str,
    *,
    directory: bool,
) -> Generator[tuple[ctypes.c_void_p, ctypes.c_void_p]]:
    with _owner_only_security_descriptor(
        sid,
        directory=directory,
    ) as descriptor:
        owner = ctypes.c_void_p()
        owner_defaulted = wintypes.BOOL()
        get_owner = ctypes.windll.advapi32.GetSecurityDescriptorOwner
        get_owner.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.BOOL),
        ]
        get_owner.restype = wintypes.BOOL
        if not get_owner(
            descriptor,
            ctypes.byref(owner),
            ctypes.byref(owner_defaulted),
        ) or not owner:
            raise ctypes.WinError()
        dacl_present = wintypes.BOOL()
        dacl_defaulted = wintypes.BOOL()
        dacl = ctypes.c_void_p()
        get_dacl = ctypes.windll.advapi32.GetSecurityDescriptorDacl
        get_dacl.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.BOOL),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.BOOL),
        ]
        get_dacl.restype = wintypes.BOOL
        if not get_dacl(
            descriptor,
            ctypes.byref(dacl_present),
            ctypes.byref(dacl),
            ctypes.byref(dacl_defaulted),
        ) or not dacl_present:
            raise ctypes.WinError()
        yield owner, dacl


def create_windows_private_temp(
    directory: Path,
    *,
    prefix: str,
) -> tuple[int, str]:
    import msvcrt

    system_root = os.environ.get("SystemRoot")
    if not system_root:
        raise OSError("cannot locate Windows security tools")
    sid = _current_windows_owner_sid(system_root)
    path = directory / f"{prefix}{secrets.token_hex(16)}.tmp"
    handle: int | None = None
    with _owner_only_security_descriptor(
        sid,
        directory=False,
    ) as security_descriptor:
        attributes = _SecurityAttributes(
            ctypes.sizeof(_SecurityAttributes),
            security_descriptor,
            False,
        )
        create_file = ctypes.windll.kernel32.CreateFileW
        create_file.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(_SecurityAttributes),
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        create_file.restype = wintypes.HANDLE
        try:
            raw_handle = create_file(
                str(path),
                0xC0000000,
                0,
                ctypes.byref(attributes),
                1,
                0x80,
                None,
            )
            if not isinstance(raw_handle, int):
                raise OSError("Windows did not return a file handle")
            handle = raw_handle
            if handle == ctypes.c_void_p(-1).value:
                handle = None
                raise ctypes.WinError()
            descriptor = msvcrt.open_osfhandle(handle, os.O_RDWR)
            handle = None
            return descriptor, str(path)
        finally:
            if handle is not None:
                close_handle = ctypes.windll.kernel32.CloseHandle
                close_handle.argtypes = [wintypes.HANDLE]
                close_handle.restype = wintypes.BOOL
                _ = close_handle(handle)
                path.unlink(missing_ok=True)


def publish_windows_private_temp(
    temporary: Path,
    destination: Path,
) -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    move = kernel32.MoveFileExW
    move.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
    ]
    move.restype = wintypes.BOOL
    if move(
        str(temporary),
        str(destination),
        _MOVEFILE_WRITE_THROUGH,
    ):
        return True
    error = ctypes.get_last_error()
    if error in {_ERROR_FILE_EXISTS, _ERROR_ALREADY_EXISTS}:
        return False
    raise ctypes.WinError(error)


def _run(command: list[str]) -> bytes:
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        message = (
            result.stderr.decode(errors="replace").strip()
            or result.stdout.decode(errors="replace").strip()
        )
        raise OSError(message or "failed to secure Native authority file")
    return result.stdout
