from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Protocol, cast

__all__ = [
    "_CloseCall",
    "_is_process_in_job",
    "_process_handle_count",
    "_top_level_windows_for_pid",
]


class _WinCall(Protocol):
    argtypes: list[object]
    restype: object

    def __call__(self, *args: object) -> int: ...


class _CloseCall(Protocol):
    def __call__(self, handle: int) -> int | None: ...


def _kernel_call(name: str) -> _WinCall:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    return cast(_WinCall, cast(object, getattr(kernel32, name)))


def _user_call(name: str) -> _WinCall:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    return cast(_WinCall, cast(object, getattr(user32, name)))


def _process_handle_count() -> int:
    count = wintypes.DWORD()
    get_count = _kernel_call("GetProcessHandleCount")
    get_count.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    get_count.restype = wintypes.BOOL
    assert get_count(wintypes.HANDLE(-1), ctypes.byref(count))
    return count.value


def _is_process_in_job(pid: int) -> bool:
    open_process = _kernel_call("OpenProcess")
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    in_job = _kernel_call("IsProcessInJob")
    in_job.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    in_job.restype = wintypes.BOOL
    close = _kernel_call("CloseHandle")
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    handle = open_process(0x1000, False, pid)
    assert handle
    result = wintypes.BOOL()
    try:
        assert in_job(handle, None, ctypes.byref(result))
    finally:
        assert close(handle)
    return bool(result.value)


def _top_level_windows_for_pid(pid: int) -> list[int]:
    windows: list[int] = []
    get_pid = _user_call("GetWindowThreadProcessId")
    visible = _user_call("IsWindowVisible")
    enumerate_windows = _user_call("EnumWindows")
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd: int, _parameter: int) -> bool:
        owner = wintypes.DWORD()
        _ = get_pid(hwnd, ctypes.byref(owner))
        if owner.value == pid and visible(hwnd):
            windows.append(hwnd)
        return True

    callback = callback_type(visit)
    assert enumerate_windows(callback, 0)
    return windows
