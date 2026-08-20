"""Windows handle I/O used by pinned curation notes."""

from __future__ import annotations

from typing import Any


def link_count(kernel32: Any, handle: int) -> int:
    import ctypes
    from ctypes import wintypes

    class FileInformation(ctypes.Structure):
        _fields_ = [
            ("attributes", wintypes.DWORD),
            ("creation", wintypes.FILETIME),
            ("access", wintypes.FILETIME),
            ("write", wintypes.FILETIME),
            ("volume", wintypes.DWORD),
            ("size_high", wintypes.DWORD),
            ("size_low", wintypes.DWORD),
            ("links", wintypes.DWORD),
            ("index_high", wintypes.DWORD),
            ("index_low", wintypes.DWORD),
        ]

    get_information = kernel32.GetFileInformationByHandle
    get_information.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
    ]
    get_information.restype = wintypes.BOOL
    result = FileInformation()
    if not get_information(
        wintypes.HANDLE(handle),
        ctypes.byref(result),
    ):
        raise OSError(ctypes.get_last_error())
    return int(result.links)


def _seek_start(kernel32: Any, handle: int) -> None:
    import ctypes
    from ctypes import wintypes

    set_pointer = kernel32.SetFilePointerEx
    set_pointer.argtypes = [
        wintypes.HANDLE,
        ctypes.c_longlong,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    set_pointer.restype = wintypes.BOOL
    if not set_pointer(
        wintypes.HANDLE(handle),
        0,
        None,
        0,
    ):
        raise OSError(ctypes.get_last_error())


def read_handle(kernel32: Any, handle: int) -> bytes:
    import ctypes
    from ctypes import wintypes

    _seek_start(kernel32, handle)
    read_file = kernel32.ReadFile
    read_file.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.LPDWORD,
        wintypes.LPVOID,
    ]
    read_file.restype = wintypes.BOOL
    chunks: list[bytes] = []
    while True:
        buffer = ctypes.create_string_buffer(64 * 1024)
        read = wintypes.DWORD()
        if not read_file(
            wintypes.HANDLE(handle),
            buffer,
            len(buffer),
            ctypes.byref(read),
            None,
        ):
            raise OSError(ctypes.get_last_error())
        if read.value == 0:
            return b"".join(chunks)
        chunks.append(buffer.raw[:read.value])


def write_handle(
    kernel32: Any,
    handle: int,
    payload: bytes,
) -> None:
    import ctypes
    from ctypes import wintypes

    _seek_start(kernel32, handle)
    set_end = kernel32.SetEndOfFile
    set_end.argtypes = [wintypes.HANDLE]
    set_end.restype = wintypes.BOOL
    if not set_end(wintypes.HANDLE(handle)):
        raise OSError(ctypes.get_last_error())
    write_file = kernel32.WriteFile
    write_file.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCVOID,
        wintypes.DWORD,
        wintypes.LPDWORD,
        wintypes.LPVOID,
    ]
    write_file.restype = wintypes.BOOL
    buffer = ctypes.create_string_buffer(payload)
    written = wintypes.DWORD()
    if not write_file(
        wintypes.HANDLE(handle),
        buffer,
        len(payload),
        ctypes.byref(written),
        None,
    ) or written.value != len(payload):
        raise OSError(ctypes.get_last_error() or 1)
    flush = kernel32.FlushFileBuffers
    flush.argtypes = [wintypes.HANDLE]
    flush.restype = wintypes.BOOL
    if not flush(wintypes.HANDLE(handle)):
        raise OSError(ctypes.get_last_error())
