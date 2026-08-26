"""Synchronous Windows ConPTY process ownership."""

from __future__ import annotations

import ctypes
import queue
import subprocess
import threading
import time
from collections import deque
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import final

from birkin._winjob import WindowsJob, WindowsStartGate

import birkin.workspace._windows_conpty_abi as _abi

__all__ = ["COORD", "WindowsConPtyProcess", "conpty_supported", "launch_windows_terminal_process"]

COORD = _abi.COORD
conpty_supported = _abi.conpty_supported
_create_process = _abi.create_process
_close_handle = _abi.close_handle
_close_pseudo_console = _abi.close_pseudo_console


@dataclass(slots=True)
class _WriteRequest:
    data: bytes
    done: threading.Event
    error: OSError | None = None


@final
class WindowsConPtyProcess:
    """Own a contained process, pseudoconsole, pipes, and blocking workers."""

    def __init__(self, pid: int, process: int, hpcon: int, input_handle: int, output_handle: int, job: WindowsJob) -> None:
        self.pid, self._process, self._hpcon = pid, process, hpcon
        self._input, self._output, self._job = input_handle, output_handle, job
        self._lock, self._condition = threading.RLock(), threading.Condition()
        self._chunks: deque[bytes] = deque()
        self._buffered, self._eof, self._closed = 0, False, False
        self._status: int | None = None
        self._writes: queue.Queue[_WriteRequest | None] = queue.Queue(maxsize=64)
        self._reader = threading.Thread(target=self._read_worker, name=f"birkin-conpty-reader-{pid}")
        self._writer = threading.Thread(target=self._write_worker, name=f"birkin-conpty-writer-{pid}")
        self._waiter = threading.Thread(target=self._wait_worker, name=f"birkin-conpty-waiter-{pid}")
        self._reader.start()
        self._writer.start()
        self._waiter.start()

    def poll(self) -> int | None:
        with self._lock:
            return self._status

    def read(self, max_bytes: int, timeout: float) -> bytes:
        if max_bytes <= 0 or timeout < 0:
            raise _abi.ConPtyConfigurationError
        deadline = time.monotonic() + timeout
        with self._condition:
            while not self._chunks and not self._eof:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self._condition.wait(remaining):
                    return b""
            if not self._chunks:
                return b""
            chunk = self._chunks.popleft()
            data, remainder = chunk[:max_bytes], chunk[max_bytes:]
            if remainder:
                self._chunks.appendleft(remainder)
            self._buffered -= len(data)
            self._condition.notify_all()
            return data

    def write(self, data: bytes, timeout: float) -> None:
        if not data or timeout < 0:
            raise _abi.ConPtyConfigurationError
        request, deadline = _WriteRequest(bytes(data), threading.Event()), time.monotonic() + timeout
        try:
            self._writes.put(request, timeout=max(0.0, deadline - time.monotonic()))
        except queue.Full:
            self.close(1)
            raise TimeoutError from None
        if not request.done.wait(max(0.0, deadline - time.monotonic())):
            self.close(1)
            raise TimeoutError
        if request.error is not None:
            raise request.error

    def resize(self, columns: int, rows: int) -> None:
        with self._lock:
            hpcon = self._hpcon
        if hpcon is None:
            raise BrokenPipeError
        _abi.check_hresult("ResizePseudoConsole", int(_abi.resize_pseudo_console(hpcon, _abi.coord(columns, rows)) or 0))

    def signal(self, name: str) -> None:
        if name != "INT":
            raise _abi.ConPtyConfigurationError
        self.write(b"\x03", 10.0)

    def close(self, exit_code: int = 1) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._status is None:
                self._status = exit_code
            input_handle, self._input = self._input, None
            process = self._process
        if input_handle is not None:
            _ = _close_handle(input_handle)
        self._writes.put(None)
        self._job.terminate(exit_code)
        if process is not None:
            _ = _abi.wait(process, 10_000)
        with self._lock:
            hpcon, self._hpcon = self._hpcon, None
        if hpcon is not None:
            _ = _close_pseudo_console(hpcon)
        self._waiter.join(10.0)
        self._reader.join(10.0)
        with self._lock:
            output_handle, self._output = self._output, None
            process, self._process = self._process, None
        if self._reader.is_alive() and output_handle is not None:
            _ = _close_handle(output_handle)
            output_handle = None
            self._reader.join(10.0)
        self._writer.join(10.0)
        if output_handle is not None:
            _ = _close_handle(output_handle)
        if process is not None:
            _ = _close_handle(process)
        self._job.close()
        if any(worker.is_alive() for worker in (self._reader, self._writer, self._waiter)):
            raise TimeoutError

    def _wait_worker(self) -> None:
        _ = _abi.wait(self._process, _abi.INFINITE)
        code = wintypes.DWORD()
        if _abi.get_exit_code(self._process, ctypes.byref(code)):
            with self._lock:
                if self._status is None:
                    self._status = int(code.value)
                hpcon, self._hpcon = self._hpcon, None
            if hpcon is not None:
                _ = _close_pseudo_console(hpcon)

    def _read_worker(self) -> None:
        while True:
            with self._lock:
                handle = self._output
            if handle is None:
                break
            buffer, count = ctypes.create_string_buffer(_abi.BUFFER_SIZE), wintypes.DWORD()
            if not _abi.read_file(handle, buffer, _abi.BUFFER_SIZE, ctypes.byref(count), None) or count.value == 0:
                break
            chunk = buffer.raw[: count.value]
            with self._condition:
                while self._buffered + len(chunk) > _abi.MAX_BUFFERED_OUTPUT and self._output is not None:
                    _ = self._condition.wait()
                self._chunks.append(chunk)
                self._buffered += len(chunk)
                self._condition.notify_all()
        with self._condition:
            self._eof = True
            self._condition.notify_all()

    def _write_worker(self) -> None:
        while (request := self._writes.get()) is not None:
            offset = 0
            while offset < len(request.data):
                with self._lock:
                    handle = self._input
                if handle is None:
                    request.error = BrokenPipeError()
                    break
                count = wintypes.DWORD()
                view = (ctypes.c_char * (len(request.data) - offset)).from_buffer_copy(request.data[offset:])
                if not _abi.write_file(handle, view, len(view), ctypes.byref(count), None):
                    request.error = _abi.error("WriteFile")
                    break
                offset += count.value
            _ = request.done.set()


def launch_windows_terminal_process(shell_path: Path, cwd: Path, environment: dict[str, str], columns: int, rows: int) -> WindowsConPtyProcess:
    """Launch cmd behind ConPTY after start-gated Job assignment."""
    size = _abi.coord(columns, rows)
    shell, directory = shell_path.resolve(strict=True), cwd.resolve(strict=True)
    if not shell.is_file() or not directory.is_dir() or any("\0" in key or "=" in key or "\0" in value for key, value in environment.items()):
        raise _abi.ConPtyConfigurationError
    job, gate = WindowsJob.create(), None
    con_in = host_in = host_out = con_out = hpcon = process = thread = None
    attribute = None
    attribute_initialized, assigned, job_transferred = False, False, False
    try:
        gate = WindowsStartGate.create()
        security = _abi.SECURITY_ATTRIBUTES(ctypes.sizeof(_abi.SECURITY_ATTRIBUTES), None, True)
        con_in_value, host_in_value, host_out_value, con_out_value = wintypes.HANDLE(), wintypes.HANDLE(), wintypes.HANDLE(), wintypes.HANDLE()
        if not _abi.create_pipe(ctypes.byref(con_in_value), ctypes.byref(host_in_value), ctypes.byref(security), 0) or not _abi.create_pipe(ctypes.byref(host_out_value), ctypes.byref(con_out_value), ctypes.byref(security), 0):
            raise _abi.error("CreatePipe")
        con_in, host_in = int(con_in_value.value or 0), int(host_in_value.value or 0)
        host_out, con_out = int(host_out_value.value or 0), int(con_out_value.value or 0)
        if not _abi.set_handle_information(host_in, _abi.HANDLE_FLAG_INHERIT, 0) or not _abi.set_handle_information(host_out, _abi.HANDLE_FLAG_INHERIT, 0):
            raise _abi.error("SetHandleInformation")
        hpcon_value = ctypes.c_void_p()
        _abi.check_hresult("CreatePseudoConsole", int(_abi.create_pseudo_console(size, con_in, con_out, 0, ctypes.byref(hpcon_value)) or 0))
        hpcon = int(hpcon_value.value or 0)
        _ = _close_handle(con_in)
        con_in = None
        _ = _close_handle(con_out)
        con_out = None
        attribute_size = ctypes.c_size_t()
        _ = _abi.initialize_attribute_list(None, 1, 0, ctypes.byref(attribute_size))
        attribute_buffer = ctypes.create_string_buffer(attribute_size.value)
        attribute = ctypes.cast(attribute_buffer, ctypes.c_void_p)
        if not _abi.initialize_attribute_list(attribute, 1, 0, ctypes.byref(attribute_size)):
            raise _abi.error("InitializeProcThreadAttributeList")
        attribute_initialized = True
        hpcon_argument = ctypes.c_void_p(hpcon)
        if not _abi.update_attribute(attribute, 0, _abi.PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE, hpcon_argument, ctypes.sizeof(ctypes.c_void_p), None, None):
            raise _abi.error("UpdateProcThreadAttribute")
        argv = gate.bootstrap_argv([str(shell), "/D", "/Q"])
        command = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
        env = ctypes.create_unicode_buffer("\0".join(f"{key}={value}" for key, value in sorted(environment.items(), key=lambda item: item[0].casefold())) + "\0\0")
        startup, info = _abi.STARTUPINFOEXW(), _abi.PROCESS_INFORMATION()
        _abi.configure_startup(startup, attribute)
        try:
            if not _create_process(argv[0], command, None, None, False, _abi.EXTENDED_STARTUPINFO_PRESENT | _abi.CREATE_UNICODE_ENVIRONMENT, env, str(directory), ctypes.byref(startup), ctypes.byref(info)):
                raise _abi.error("CreateProcessW")
        finally:
            _ = _abi.delete_attribute_list(attribute)
            attribute_initialized = False
        process, thread, pid = _abi.process_values(info)
        _ = _close_handle(thread)
        thread = None
        gate.wait_ready()
        job.assign(pid)
        assigned = True
        gate.release()
        gate.close()
        gate = None
        owned = WindowsConPtyProcess(pid, process, hpcon, host_in, host_out, job)
        process = hpcon = host_in = host_out = None
        job_transferred = True
        return owned
    except (OSError, RuntimeError, TimeoutError):
        if process is not None:
            if assigned:
                job.terminate(1)
            else:
                _ = _abi.terminate_process(process, 1)
            _ = _abi.wait(process, 10_000)
        raise
    finally:
        if attribute_initialized:
            _ = _abi.delete_attribute_list(attribute)
        if gate is not None:
            gate.close()
        for handle in (thread, process, con_out, host_out, host_in, con_in):
            if handle is not None:
                _ = _close_handle(handle)
        if hpcon is not None:
            _ = _close_pseudo_console(hpcon)
        if not job_transferred:
            job.close()
