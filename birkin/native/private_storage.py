"""Cross-platform owner-only permissions for Native authority files."""

from __future__ import annotations

import csv
import os
import re
import secrets
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import cast, final

_WINDOWS_SID = re.compile(rb"S-\d-\d+(?:-\d+)+")


def create_private_temp(
    directory: Path,
    *,
    prefix: str,
) -> tuple[int, str]:
    if os.name == "nt":
        return _create_windows_private_temp(directory, prefix=prefix)
    descriptor, name = tempfile.mkstemp(dir=directory, prefix=prefix)
    os.fchmod(descriptor, 0o600)
    return descriptor, name


def harden_private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == "nt":
        _harden_windows_path(path, directory=True)
    else:
        path.chmod(0o700)


def harden_private_file(path: Path) -> None:
    if os.name == "nt":
        _harden_windows_path(path, directory=False)
    else:
        path.chmod(0o600)


def _harden_windows_path(path: Path, *, directory: bool) -> None:
    system_root = os.environ.get("SystemRoot")
    if not system_root:
        raise OSError("cannot locate Windows security tools")
    system = Path(system_root) / "System32"
    identity = _windows_owner_sid(
        _run([str(system / "whoami.exe"), "/user", "/fo", "csv", "/nh"])
    )
    sid = identity
    grant = f"*{sid}:(OI)(CI)F" if directory else f"*{sid}:F"
    _ = _run([
        str(system / "icacls.exe"),
        str(path),
        "/reset",
    ])
    _ = _run([
        str(system / "icacls.exe"),
        str(path),
        "/inheritance:r",
        "/grant:r",
        grant,
    ])


def _windows_owner_sid(output: bytes) -> str:
    try:
        rows = list(csv.reader(
            output.decode("utf-8-sig").splitlines()
        ))
    except UnicodeDecodeError as error:
        raise OSError(
            "cannot identify the Windows Native file owner"
        ) from error
    if len(rows) != 1 or len(rows[0]) < 2:
        raise OSError("cannot identify the Windows Native file owner")
    sid = rows[0][-1].strip()
    if _WINDOWS_SID.fullmatch(sid.encode("ascii", errors="ignore")) is None:
        raise OSError("cannot identify the Windows Native file owner")
    return sid


def _create_windows_private_temp(
    directory: Path,
    *,
    prefix: str,
) -> tuple[int, str]:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    system_root = os.environ.get("SystemRoot")
    if not system_root:
        raise OSError("cannot locate Windows security tools")
    whoami = Path(system_root) / "System32/whoami.exe"
    sid = _windows_owner_sid(
        _run([str(whoami), "/user", "/fo", "csv", "/nh"])
    )
    security_descriptor = ctypes.c_void_p()
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
    sddl = f"D:P(A;;FA;;;{sid})"
    if not convert(
        sddl,
        1,
        ctypes.byref(security_descriptor),
        ctypes.byref(descriptor_size),
    ):
        raise ctypes.WinError()

    @final
    class SecurityAttributes(ctypes.Structure):
        _fields_ = [
            ("length", wintypes.DWORD),
            ("security_descriptor", ctypes.c_void_p),
            ("inherit_handle", wintypes.BOOL),
        ]

    attributes = SecurityAttributes(
        ctypes.sizeof(SecurityAttributes),
        security_descriptor,
        False,
    )
    path = directory / f"{prefix}{secrets.token_hex(16)}.tmp"
    create_file = ctypes.windll.kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(SecurityAttributes),
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    call_create_file = cast(
        Callable[[str, int, int, object, int, int, object], object],
        create_file,
    )
    handle: int | None = None
    try:
        raw_handle = call_create_file(
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
        invalid_handle = ctypes.c_void_p(-1).value
        if handle == invalid_handle:
            handle = None
            raise ctypes.WinError()
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDWR)
        handle = None
        return descriptor, str(path)
    finally:
        if handle is not None:
            close_handle = cast(
                Callable[[int], object],
                ctypes.windll.kernel32.CloseHandle,
            )
            _ = close_handle(handle)
        local_free = cast(
            Callable[[object], object],
            ctypes.windll.kernel32.LocalFree,
        )
        _ = local_free(security_descriptor)


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
