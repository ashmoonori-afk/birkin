"""Windows Job Object ownership for managed shell process trees."""

from __future__ import annotations

import base64
import ctypes
import json
import sys
import uuid
from collections.abc import Sequence
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast, final

_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100
_SYNCHRONIZE = 0x00100000
_WAIT_OBJECT_0 = 0
_START_GATE_TIMEOUT_MS = 30_000


@final
class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


@final
class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


@final
class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

class _CreateJob(Protocol):
    argtypes: list[object]
    restype: object

    def __call__(
        self,
        attributes: object | None,
        name: str | None,
    ) -> int: ...


class _SetJobInformation(Protocol):
    argtypes: list[object]
    restype: object

    def __call__(
        self,
        handle: int,
        information_class: int,
        information: object,
        length: int,
    ) -> int: ...


class _OpenProcess(Protocol):
    argtypes: list[object]
    restype: object

    def __call__(self, access: int, inherit: bool, pid: int) -> int: ...


class _AssignProcess(Protocol):
    argtypes: list[object]
    restype: object

    def __call__(self, job: int, process: int) -> int: ...


class _TerminateJob(Protocol):
    argtypes: list[object]
    restype: object

    def __call__(self, job: int, exit_code: int) -> int: ...


class _CreateEvent(Protocol):
    argtypes: list[object]
    restype: object

    def __call__(
        self,
        attributes: object | None,
        manual_reset: bool,
        initial_state: bool,
        name: str,
    ) -> int: ...


class _SetEvent(Protocol):
    argtypes: list[object]
    restype: object

    def __call__(self, event: int) -> int: ...


class _Wait(Protocol):
    argtypes: list[object]
    restype: object

    def __call__(self, handle: int, timeout_ms: int) -> int: ...


class _CloseHandle(Protocol):
    argtypes: list[object]
    restype: object

    def __call__(self, handle: int) -> int: ...


class _BasicLimitFields(Protocol):
    LimitFlags: int


class _ExtendedLimitFields(Protocol):
    BasicLimitInformation: _BasicLimitInformation


_create_job = cast(
    _CreateJob,
    cast(object, _kernel32.CreateJobObjectW),
)
_create_job.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
_create_job.restype = wintypes.HANDLE

_set_job_information = cast(
    _SetJobInformation,
    cast(object, _kernel32.SetInformationJobObject),
)
_set_job_information.argtypes = [
    wintypes.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    wintypes.DWORD,
]
_set_job_information.restype = wintypes.BOOL

_open_process = cast(
    _OpenProcess,
    cast(object, _kernel32.OpenProcess),
)
_open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_open_process.restype = wintypes.HANDLE

_assign_process = cast(
    _AssignProcess,
    cast(object, _kernel32.AssignProcessToJobObject),
)
_assign_process.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
_assign_process.restype = wintypes.BOOL

_terminate_job = cast(
    _TerminateJob,
    cast(object, _kernel32.TerminateJobObject),
)
_terminate_job.argtypes = [wintypes.HANDLE, wintypes.UINT]
_terminate_job.restype = wintypes.BOOL

_create_event = cast(
    _CreateEvent,
    cast(object, _kernel32.CreateEventW),
)
_create_event.argtypes = [
    ctypes.c_void_p,
    wintypes.BOOL,
    wintypes.BOOL,
    wintypes.LPCWSTR,
]
_create_event.restype = wintypes.HANDLE

_set_event = cast(_SetEvent, cast(object, _kernel32.SetEvent))
_set_event.argtypes = [wintypes.HANDLE]
_set_event.restype = wintypes.BOOL

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


def _windows_error(message: str) -> OSError:
    return ctypes.WinError(ctypes.get_last_error(), message)


def job_layout_sizes() -> tuple[int, int, int]:
    """Return ctypes sizes for the WinNT Job Object structures."""
    return (
        ctypes.sizeof(_IoCounters),
        ctypes.sizeof(_BasicLimitInformation),
        ctypes.sizeof(_ExtendedLimitInformation),
    )


@dataclass(slots=True)
class WindowsJob:
    """A kill-on-close Windows Job Object."""

    _handle: int | None

    @classmethod
    def create(cls) -> WindowsJob:
        handle = _create_job(None, None)
        if not handle:
            raise _windows_error("CreateJobObjectW failed")
        job = cls(handle)
        limits = _ExtendedLimitInformation()
        basic_limits = _BasicLimitInformation()
        basic_view = cast(
            _BasicLimitFields,
            cast(object, basic_limits),
        )
        basic_view.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        limits_view = cast(
            _ExtendedLimitFields,
            cast(object, limits),
        )
        limits_view.BasicLimitInformation = basic_limits
        if not _set_job_information(
            handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            error = _windows_error("SetInformationJobObject failed")
            job.close()
            raise error
        return job

    def assign(self, pid: int) -> None:
        handle = self._require_handle()
        process = _open_process(
            _PROCESS_TERMINATE | _PROCESS_SET_QUOTA,
            False,
            pid,
        )
        if not process:
            raise _windows_error("OpenProcess failed")
        try:
            if not _assign_process(handle, process):
                raise _windows_error("AssignProcessToJobObject failed")
        finally:
            _ = _close_handle(process)

    def terminate(self, exit_code: int = 1) -> None:
        handle = self._handle
        if handle:
            _ = _terminate_job(handle, exit_code)

    def close(self) -> None:
        handle, self._handle = self._handle, None
        if handle:
            _ = _close_handle(handle)

    def _require_handle(self) -> int:
        if not self._handle:
            raise RuntimeError("Windows Job Object is closed")
        return self._handle


@dataclass(slots=True)
class WindowsStartGate:
    """Two-event handshake that gates the bootstrap before shell creation."""

    release_name: str
    ready_name: str
    _release_handle: int | None
    _ready_handle: int | None

    @classmethod
    def create(cls) -> WindowsStartGate:
        token = uuid.uuid4().hex
        release_name = f"Local\\BirkinJob-{token}-release"
        ready_name = f"Local\\BirkinJob-{token}-ready"
        release_handle = _create_event(None, True, False, release_name)
        if not release_handle:
            raise _windows_error("CreateEventW failed")
        ready_handle = _create_event(None, True, False, ready_name)
        if not ready_handle:
            _ = _close_handle(release_handle)
            raise _windows_error("CreateEventW failed")
        return cls(
            release_name,
            ready_name,
            release_handle,
            ready_handle,
        )

    def bootstrap_argv(self, argv: Sequence[str]) -> list[str]:
        payload = json.dumps(list(argv), ensure_ascii=False).encode("utf-8")
        encoded = base64.urlsafe_b64encode(payload).decode("ascii")
        bootstrap = Path(__file__).with_name(
            "_winjob_bootstrap.py"
        ).resolve()
        return [
            str(Path(sys.base_prefix) / Path(sys.executable).name),
            "-I",
            "-S",
            str(bootstrap),
            self.release_name,
            self.ready_name,
            encoded,
        ]

    def wait_ready(self) -> None:
        handle = self._require_ready_handle()
        result = _wait(handle, _START_GATE_TIMEOUT_MS)
        if result != _WAIT_OBJECT_0:
            raise _windows_error("bootstrap readiness wait failed")

    def release(self) -> None:
        handle = self._require_release_handle()
        if not _set_event(handle):
            raise _windows_error("SetEvent failed")

    def close(self) -> None:
        release, self._release_handle = self._release_handle, None
        ready, self._ready_handle = self._ready_handle, None
        if release:
            _ = _close_handle(release)
        if ready:
            _ = _close_handle(ready)

    def _require_release_handle(self) -> int:
        if not self._release_handle:
            raise RuntimeError("Windows start gate is closed")
        return self._release_handle

    def _require_ready_handle(self) -> int:
        if not self._ready_handle:
            raise RuntimeError("Windows start gate is closed")
        return self._ready_handle
