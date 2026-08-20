"""Windows namespace locking for complete skill-bundle publication."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .bundle_publish import BundleSnapshot
from .manager import _windows_kernel32


@contextmanager
def _locked_parent(
    target_root: Path,
    relative_parent: Path,
) -> Iterator[Path]:
    import ctypes
    from ctypes import wintypes

    kernel32 = _windows_kernel32()
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
    handles: list[int] = []
    current = target_root

    class FileAttributeTagInfo(ctypes.Structure):
        _fields_ = [
            ("FileAttributes", wintypes.DWORD),
            ("ReparseTag", wintypes.DWORD),
        ]

    try:
        for part in (None, *relative_parent.parts):
            if part is not None:
                current /= part
                if not current.exists():
                    if not kernel32.CreateDirectoryW(str(current), None):
                        raise OSError(
                            ctypes.get_last_error(),
                            str(current),
                        )
            handle = create_file(
                str(current),
                0x0080,
                0x00000001 | 0x00000002,
                None,
                3,
                0x02000000 | 0x00200000,
                None,
            )
            if handle == wintypes.HANDLE(-1).value:
                raise OSError(ctypes.get_last_error(), str(current))
            info = FileAttributeTagInfo()
            if not kernel32.GetFileInformationByHandleEx(
                handle,
                9,
                ctypes.byref(info),
                ctypes.sizeof(info),
            ):
                kernel32.CloseHandle(handle)
                raise OSError(ctypes.get_last_error(), str(current))
            if info.FileAttributes & 0x00000400:
                kernel32.CloseHandle(handle)
                raise OSError(
                    "skill mirror parent is a reparse point"
                )
            handles.append(int(handle))
        yield current
    finally:
        active_error = sys.exc_info()[1]
        close_error = 0
        for handle in reversed(handles):
            if not kernel32.CloseHandle(wintypes.HANDLE(handle)):
                close_error = (
                    close_error
                    or ctypes.get_last_error()
                    or 1
                )
        if close_error and active_error is None:
            raise OSError(close_error, str(current))


def _populate(root: Path, snapshot: BundleSnapshot) -> None:
    for relative in snapshot.directories:
        (root / Path(relative.as_posix())).mkdir(parents=True)
    for entry in snapshot.files:
        path = root / Path(entry.relative.as_posix())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(entry.payload)
        path.chmod(entry.mode)


def publish_windows(
    snapshot: BundleSnapshot,
    target: Path,
    target_root: Path,
    replace: bool,
) -> bool:
    relative = target.relative_to(target_root)
    with _locked_parent(target_root, relative.parent) as parent:
        destination = parent / relative.name
        if os.path.lexists(destination) and not replace:
            return False
        operation = Path(
            tempfile.mkdtemp(prefix=".birkin-sync-", dir=parent)
        )
        previous = operation / "previous"
        candidate = operation / "candidate"
        candidate.mkdir()
        try:
            _populate(candidate, snapshot)
            if os.path.lexists(destination):
                destination.replace(previous)
            try:
                candidate.replace(destination)
            except OSError:
                if previous.exists():
                    previous.replace(destination)
                raise
            if previous.exists():
                shutil.rmtree(previous)
            return True
        finally:
            shutil.rmtree(operation, ignore_errors=True)
