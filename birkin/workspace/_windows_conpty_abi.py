"""Stateless typed Win32 declarations for the ConPTY owner."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Final, Protocol, cast, final

BUFFER_SIZE: Final = 16_384
MAX_BUFFERED_OUTPUT: Final = 1_048_576
PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE: Final = 0x00020016
EXTENDED_STARTUPINFO_PRESENT: Final = 0x00080000
CREATE_UNICODE_ENVIRONMENT: Final = 0x00000400
STARTF_USESTDHANDLES: Final = 0x00000100
HANDLE_FLAG_INHERIT: Final = 0x00000001
INFINITE: Final = 0xFFFFFFFF


@final
class COORD(ctypes.Structure):
    _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]


@final
class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p), ("bInheritHandle", wintypes.BOOL)]


@final
class STARTUPINFOW(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD), ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD), ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD), ("lpReserved2", ctypes.POINTER(ctypes.c_ubyte)), ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE)]


@final
class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]


@final
class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE), ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]


class WinCall(Protocol):
    argtypes: list[object]
    restype: object

    def __call__(self, *args: object) -> int | None: ...


class _StartupFields(Protocol):
    cb: int
    dwFlags: int
    hStdInput: int | None
    hStdOutput: int | None
    hStdError: int | None


class _StartupExFields(Protocol):
    StartupInfo: _StartupFields
    lpAttributeList: int


class _ProcessFields(Protocol):
    hProcess: int
    hThread: int
    dwProcessId: int


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


def _bind(name: str, argtypes: list[object], restype: object) -> WinCall:
    call = cast(WinCall, cast(object, getattr(_kernel32, name)))
    call.argtypes, call.restype = argtypes, restype
    return call


create_pipe = _bind("CreatePipe", [ctypes.POINTER(wintypes.HANDLE), ctypes.POINTER(wintypes.HANDLE), ctypes.POINTER(SECURITY_ATTRIBUTES), wintypes.DWORD], wintypes.BOOL)
set_handle_information = _bind("SetHandleInformation", [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD], wintypes.BOOL)
create_pseudo_console = _bind("CreatePseudoConsole", [COORD, wintypes.HANDLE, wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)], ctypes.c_long)
resize_pseudo_console = _bind("ResizePseudoConsole", [ctypes.c_void_p, COORD], ctypes.c_long)
close_pseudo_console = _bind("ClosePseudoConsole", [ctypes.c_void_p], None)
initialize_attribute_list = _bind("InitializeProcThreadAttributeList", [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t)], wintypes.BOOL)
update_attribute = _bind("UpdateProcThreadAttribute", [ctypes.c_void_p, wintypes.DWORD, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p], wintypes.BOOL)
delete_attribute_list = _bind("DeleteProcThreadAttributeList", [ctypes.c_void_p], None)
create_process = _bind("CreateProcessW", [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(STARTUPINFOEXW), ctypes.POINTER(PROCESS_INFORMATION)], wintypes.BOOL)
read_file = _bind("ReadFile", [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p], wintypes.BOOL)
write_file = _bind("WriteFile", [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p], wintypes.BOOL)
wait = _bind("WaitForSingleObject", [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD)
get_exit_code = _bind("GetExitCodeProcess", [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL)
terminate_process = _bind("TerminateProcess", [wintypes.HANDLE, wintypes.UINT], wintypes.BOOL)
close_handle = _bind("CloseHandle", [wintypes.HANDLE], wintypes.BOOL)


class ConPtyConfigurationError(ValueError):
    """The requested ConPTY launch configuration is invalid."""


def configure_startup(startup: STARTUPINFOEXW, attribute: ctypes.c_void_p) -> None:
    fields = cast(_StartupExFields, cast(object, startup))
    fields.StartupInfo.cb = ctypes.sizeof(startup)
    fields.lpAttributeList = int(attribute.value or 0)
    fields.StartupInfo.dwFlags = STARTF_USESTDHANDLES
    fields.StartupInfo.hStdInput = None
    fields.StartupInfo.hStdOutput = None
    fields.StartupInfo.hStdError = None


def process_values(info: PROCESS_INFORMATION) -> tuple[int, int, int]:
    fields = cast(_ProcessFields, cast(object, info))
    return fields.hProcess, fields.hThread, fields.dwProcessId


def error(api: str) -> OSError:
    return ctypes.WinError(ctypes.get_last_error(), f"{api} failed")


def check_hresult(api: str, result: int) -> None:
    if result < 0:
        raise OSError(result & 0xFFFFFFFF, f"{api} failed")


def coord(columns: int, rows: int) -> COORD:
    if not 1 <= columns <= 1000 or not 1 <= rows <= 1000:
        raise ConPtyConfigurationError
    return COORD(columns, rows)


def conpty_supported() -> bool:
    """Return whether this host exposes the supported ConPTY ABI."""
    return sys.platform == "win32" and sys.getwindowsversion().build >= 17763 and all(hasattr(_kernel32, name) for name in ("CreatePseudoConsole", "ResizePseudoConsole", "ClosePseudoConsole"))
