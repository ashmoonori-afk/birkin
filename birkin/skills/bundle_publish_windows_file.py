"""Locked Windows tree creation for bundle publication."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from .bundle_publish import BundleSnapshot
from .bundle_publish_windows_io import (
    CREATE_NEW,
    DELETE,
    GENERIC_WRITE,
    READ_ATTRIBUTES,
    REPARSE_ATTRIBUTE,
    close,
    information,
    open_handle,
)
from .bundle_publish_windows_native import (
    create_directory_handle,
)
from .bundle_publish_windows_tree import TreeHandles

def _write_file(
    kernel32: Any,
    path: Path,
    payload: bytes,
) -> int:
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
        return handle
    except BaseException:
        close(kernel32, handle)
        raise


def populate(
    kernel32: Any,
    candidate: Path,
    candidate_handle: int,
    snapshot: BundleSnapshot,
    handles: TreeHandles,
) -> None:
    directory_handles: dict[PurePosixPath, int] = {}
    for relative in snapshot.directories:
        path = candidate / Path(relative.as_posix())
        parent = relative.parent
        parent_handle = (
            candidate_handle
            if parent == PurePosixPath(".")
            else directory_handles[parent]
        )
        handle = create_directory_handle(
            parent_handle,
            path.parent,
            path.name,
            access=READ_ATTRIBUTES | DELETE,
            share=0x00000001 | 0x00000002,
        )
        handles.directories.append(handle)
        attributes, _ = information(kernel32, handle)
        if attributes & REPARSE_ATTRIBUTE:
            raise OSError("bundle directory is a reparse point")
        directory_handles[relative] = handle
    for entry in snapshot.files:
        path = candidate / Path(entry.relative.as_posix())
        handles.files.append(
            _write_file(kernel32, path, entry.payload)
        )
