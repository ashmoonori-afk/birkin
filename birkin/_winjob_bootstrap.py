"""Launch a Windows shell only after its Job Object assignment."""

from __future__ import annotations

import base64
import ctypes
import json
import ntpath
import subprocess
import sys
from ctypes import wintypes
from typing import Protocol, cast

_SYNCHRONIZE = 0x00100000
_EVENT_MODIFY_STATE = 0x0002
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


class _SetEvent(Protocol):
    argtypes: list[object]
    restype: object

    def __call__(self, handle: int) -> int: ...


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

_set_event = cast(
    _SetEvent,
    cast(object, _kernel32.SetEvent),
)
_set_event.argtypes = [wintypes.HANDLE]
_set_event.restype = wintypes.BOOL

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


def _fail(message: str) -> int:
    print(f"birkin job bootstrap: {message}", file=sys.stderr)
    return 125


def _run_shell(argv: list[str]) -> int:
    if not argv:
        return _fail("empty command argv")
    is_cmd_shell = (
        len(argv) == 5
        and ntpath.basename(argv[0]).casefold() == "cmd.exe"
        and [part.casefold() for part in argv[1:4]]
        == ["/d", "/s", "/c"]
    )
    if is_cmd_shell:
        command_line = f"{subprocess.list2cmdline(argv[:4])} {argv[4]}"
        return subprocess.run(
            command_line,
            executable=argv[0],
            check=False,
        ).returncode
    return subprocess.run(argv, check=False).returncode


def main() -> int:
    if len(sys.argv) != 4:
        return _fail("invalid argument count")
    release_event = _open_event(_SYNCHRONIZE, False, sys.argv[1])
    if not release_event:
        return _fail("release event unavailable")
    ready_event = _open_event(_EVENT_MODIFY_STATE, False, sys.argv[2])
    if not ready_event:
        _ = _close_handle(release_event)
        return _fail("ready event unavailable")
    try:
        if not _set_event(ready_event):
            return _fail("readiness signal failed")
        if _wait(
            release_event,
            _BOOTSTRAP_TIMEOUT_MS,
        ) != _WAIT_OBJECT_0:
            return _fail("release wait failed")
    finally:
        _ = _close_handle(ready_event)
        _ = _close_handle(release_event)
    argv = _decode_argv(sys.argv[3])
    if argv is None:
        return _fail("invalid command payload")
    return _run_shell(argv)


if __name__ == "__main__":
    raise SystemExit(main())
