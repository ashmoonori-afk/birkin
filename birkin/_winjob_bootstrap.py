"""Launch a Windows shell only after its Job Object assignment."""

from __future__ import annotations

import base64
import ctypes
import json
import subprocess
import sys
from ctypes import wintypes
from typing import Protocol, cast

_SYNCHRONIZE = 0x00100000
_WAIT_OBJECT_0 = 0
_BOOTSTRAP_TIMEOUT_MS = 30_000

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

class _OpenEvent(Protocol):
    argtypes: list[object]
    restype: object

    def __call__(self, access: int, inherit: bool, name: str) -> int: ...


class _Wait(Protocol):
    argtypes: list[object]
    restype: object

    def __call__(self, handle: int, timeout_ms: int) -> int: ...


class _CloseHandle(Protocol):
    argtypes: list[object]
    restype: object

    def __call__(self, handle: int) -> int: ...


_open_event = cast(
    _OpenEvent,
    cast(object, _kernel32.OpenEventW),
)
_open_event.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_open_event.restype = wintypes.HANDLE

_wait = cast(
    _Wait,
    cast(object, _kernel32.WaitForSingleObject),
)
_wait.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_wait.restype = wintypes.DWORD

_close_handle = cast(
    _CloseHandle,
    cast(object, _kernel32.CloseHandle),
)
_close_handle.argtypes = [wintypes.HANDLE]
_close_handle.restype = wintypes.BOOL


def _decode_argv(encoded: str) -> list[str] | None:
    try:
        payload = base64.urlsafe_b64decode(encoded).decode("utf-8")
        value = cast(object, json.loads(payload))
    except (ValueError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, list):
        return None
    items = cast(list[object], value)
    if not all(
        isinstance(item, str) for item in items
    ):
        return None
    return [item for item in items if isinstance(item, str)]


def main() -> int:
    if len(sys.argv) != 3:
        return 125
    event = _open_event(_SYNCHRONIZE, False, sys.argv[1])
    if not event:
        return 125
    try:
        if _wait(event, _BOOTSTRAP_TIMEOUT_MS) != _WAIT_OBJECT_0:
            return 125
    finally:
        _ = _close_handle(event)
    argv = _decode_argv(sys.argv[2])
    if argv is None:
        return 125
    return subprocess.run(argv, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
