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
_SE_FILE_OBJECT = 1
_DACL_SECURITY_INFORMATION = 0x00000004
_PROTECTED_DACL_SECURITY_INFORMATION = 0x80000000


@final
class _SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.DWORD),
        ("security_descriptor", ctypes.c_void_p),
        ("inherit_handle", wintypes.BOOL),
    ]


def harden_windows_path(path: Path, *, directory: bool) -> None:
    system_root = os.environ.get("SystemRoot")
    if not system_root:
        raise OSError("cannot locate Windows security tools")
    sid = _current_windows_owner_sid(system_root)
    with _owner_only_dacl(sid, directory=directory) as dacl:
        set_info = ctypes.windll.advapi32.SetNamedSecurityInfoW
        set_info.argtypes = [
            wintypes.LPWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        set_info.restype = wintypes.DWORD
        result = set_info(
            str(path),
            _SE_FILE_OBJECT,
            _DACL_SECURITY_INFORMATION
            | _PROTECTED_DACL_SECURITY_INFORMATION,
            None,
            None,
            dacl,
            None,
        )
        if result != 0:
            raise ctypes.WinError(result)


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
    sddl = f"D:P(A;{inheritance};FA;;;{sid})"
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
def _owner_only_dacl(
    sid: str,
    *,
    directory: bool,
) -> Generator[ctypes.c_void_p]:
    with _owner_only_security_descriptor(
        sid,
        directory=directory,
    ) as descriptor:
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
        yield dacl


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
