"""Windows Job Object ownership for managed shell process trees."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from typing import Protocol, cast, final

_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_PROCESS_SUSPEND_RESUME = 0x0800


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
_ntdll = ctypes.WinDLL("ntdll")

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


class _IsProcessInJob(Protocol):
    argtypes: list[object]
    restype: object

    def __call__(
        self,
        process: int,
        job: int,
        result: object,
    ) -> int: ...


class _ResumeProcess(Protocol):
    argtypes: list[object]
    restype: object

    def __call__(self, process: int) -> int: ...


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

_is_process_in_job = cast(
    _IsProcessInJob,
    cast(object, _kernel32.IsProcessInJob),
)
_is_process_in_job.argtypes = [
    wintypes.HANDLE,
    wintypes.HANDLE,
    ctypes.POINTER(wintypes.BOOL),
]
_is_process_in_job.restype = wintypes.BOOL

_resume_process = cast(
    _ResumeProcess,
    cast(object, _ntdll.NtResumeProcess),
)
_resume_process.argtypes = [wintypes.HANDLE]
_resume_process.restype = wintypes.LONG

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

    def contains(self, pid: int) -> bool:
        handle = self._require_handle()
        process = _open_process(
            _PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            pid,
        )
        if not process:
            raise _windows_error("OpenProcess failed")
        try:
            result = wintypes.BOOL()
            if not _is_process_in_job(process, handle, ctypes.byref(result)):
                raise _windows_error("IsProcessInJob failed")
            return bool(result.value)
        finally:
            _ = _close_handle(process)

    def resume(self, pid: int) -> None:
        process = _open_process(_PROCESS_SUSPEND_RESUME, False, pid)
        if not process:
            raise _windows_error("OpenProcess failed")
        try:
            status = _resume_process(process)
            if status != 0:
                raise OSError(status, "NtResumeProcess failed")
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
