"""Locked Windows tree creation for bundle publication."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .bundle_publish import BundleSnapshot
from .bundle_publish_windows_io import (
    CREATE_NEW,
    GENERIC_WRITE,
    READ_ATTRIBUTES,
    REPARSE_ATTRIBUTE,
    close,
    information,
    open_handle,
)


def create_directory(kernel32: Any, path: Path) -> None:
    import ctypes
    from ctypes import wintypes

    create = kernel32.CreateDirectoryW
    create.argtypes = [wintypes.LPCWSTR, wintypes.LPVOID]
    create.restype = wintypes.BOOL
    if not create(str(path), None):
        raise OSError(ctypes.get_last_error(), str(path))


def _write_file(
    kernel32: Any,
    path: Path,
    payload: bytes,
) -> None:
    import ctypes
    from ctypes import wintypes

    handle = open_handle(
        kernel32,
        path,
        access=GENERIC_WRITE | READ_ATTRIBUTES,
        share=0,
        disposition=CREATE_NEW,
        directory=False,
    )
    try:
        attributes, _ = information(kernel32, handle)
        if attributes & REPARSE_ATTRIBUTE:
            raise OSError("bundle file is a reparse point")
        buffer = ctypes.create_string_buffer(payload)
        written = wintypes.DWORD()
        write_file = kernel32.WriteFile
        write_file.argtypes = [
            wintypes.HANDLE,
            wintypes.LPCVOID,
            wintypes.DWORD,
            wintypes.LPDWORD,
            wintypes.LPVOID,
        ]
        write_file.restype = wintypes.BOOL
        if not write_file(
            wintypes.HANDLE(handle),
            buffer,
            len(payload),
            ctypes.byref(written),
            None,
        ):
            raise OSError(ctypes.get_last_error(), str(path))
        if written.value != len(payload):
            raise OSError("short Windows bundle write")
        flush = kernel32.FlushFileBuffers
        flush.argtypes = [wintypes.HANDLE]
        flush.restype = wintypes.BOOL
        if not flush(wintypes.HANDLE(handle)):
            raise OSError(ctypes.get_last_error(), str(path))
    finally:
        close(kernel32, handle)


def populate(
    kernel32: Any,
    candidate: Path,
    snapshot: BundleSnapshot,
) -> None:
    directory_handles: list[int] = []
    try:
        for relative in snapshot.directories:
            path = candidate / Path(relative.as_posix())
            path.mkdir(parents=True)
            handle = open_handle(
                kernel32,
                path,
                access=READ_ATTRIBUTES,
            )
            attributes, _ = information(kernel32, handle)
            if attributes & REPARSE_ATTRIBUTE:
                close(kernel32, handle)
                raise OSError("bundle directory is a reparse point")
            directory_handles.append(handle)
        for entry in snapshot.files:
            path = candidate / Path(entry.relative.as_posix())
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_file(kernel32, path, entry.payload)
    finally:
        active_error = sys.exc_info()[1]
        close_error: OSError | None = None
        for handle in reversed(directory_handles):
            try:
                close(kernel32, handle)
            except OSError as error:
                close_error = close_error or error
        if active_error is None and close_error is not None:
            raise close_error
