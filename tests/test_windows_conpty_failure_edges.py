from __future__ import annotations

import ctypes
import os
import threading
from ctypes import wintypes
from pathlib import Path
from typing import final

import pytest
from typing_extensions import override

from birkin._winjob import WindowsJob, WindowsStartGate
from birkin.workspace import windows_conpty as conpty
import birkin.workspace._windows_conpty_abi as abi

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows ConPTY failure edges")
_TIMEOUT = 2.0


def test_second_create_pipe_failure_closes_immediately_owned_first_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a successful first CreatePipe and injected second-call failure
    calls = 0
    closed: list[int] = []
    job_closed = threading.Event()
    job = WindowsJob(None)
    gate = WindowsStartGate("release", "ready", None, None)

    def create_job() -> WindowsJob:
        return job

    def create_gate() -> WindowsStartGate:
        return gate

    def create_pipe(
        read: ctypes.c_void_p,
        write: ctypes.c_void_p,
        *_args: object,
    ) -> int:
        nonlocal calls
        calls += 1
        if calls == 2:
            _ = ctypes.set_last_error(5)
            return 0
        ctypes.cast(read, ctypes.POINTER(wintypes.HANDLE)).contents.value = 101
        ctypes.cast(write, ctypes.POINTER(wintypes.HANDLE)).contents.value = 102
        return 1

    def close_handle(handle: int) -> int:
        closed.append(handle)
        return 1

    def close_job(_job: WindowsJob) -> None:
        job_closed.set()

    monkeypatch.setattr(WindowsJob, "create", create_job)
    monkeypatch.setattr(WindowsStartGate, "create", create_gate)
    monkeypatch.setattr(abi, "create_pipe", create_pipe)
    monkeypatch.setattr("birkin.workspace.windows_conpty._close_handle", close_handle)
    monkeypatch.setattr(WindowsJob, "close", close_job)
    shell = Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe"
    # When launch rolls back from the second acquisition position
    with pytest.raises(OSError, match="CreatePipe"):
        _ = conpty.launch_windows_terminal_process(shell, tmp_path, {}, 80, 24)
    # Then the first pair already has cleanup ownership
    assert calls == 2
    assert closed == [102, 101]
    assert job_closed.is_set()


def test_close_notifies_over_budget_reader_and_joins_without_polling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a reader subscribed to exact over-budget Condition wait entry
    wait_entered = threading.Event()
    waiter_release = threading.Event()
    close_done = threading.Event()
    reader_conditions: list[threading.Condition] = []
    deferred_threads: list[threading.Thread] = []

    @final
    class SignallingCondition(threading.Condition):
        @override
        def wait(self, timeout: float | None = None) -> bool:
            if threading.current_thread().name.startswith("birkin-conpty-reader"):
                reader_conditions.append(self)
                wait_entered.set()
            return super().wait(timeout)

    reads = 0

    def read_file(
        _handle: int,
        buffer: ctypes.c_void_p,
        _size: int,
        count: ctypes.c_void_p,
        _overlapped: ctypes.c_void_p | None,
    ) -> int:
        nonlocal reads
        reads += 1
        _ = ctypes.memset(buffer, 65, abi.BUFFER_SIZE)
        ctypes.cast(count, ctypes.POINTER(wintypes.DWORD)).contents.value = abi.BUFFER_SIZE
        return 1

    def wait(_handle: int, timeout: int) -> int:
        if timeout == abi.INFINITE:
            assert waiter_release.wait(_TIMEOUT)
        return 0

    def terminate(_job: WindowsJob, _exit_code: int = 1) -> None:
        waiter_release.set()

    def close_handle(_handle: int) -> int:
        return 1

    def close_pseudo_console(_hpcon: int) -> None:
        return None

    def defer_start(thread: threading.Thread) -> None:
        deferred_threads.append(thread)

    def unavailable_exit_code(*_args: object) -> int:
        return 0

    monkeypatch.setattr(abi, "read_file", read_file)
    monkeypatch.setattr(abi, "wait", wait)
    monkeypatch.setattr(abi, "get_exit_code", unavailable_exit_code)
    monkeypatch.setattr("birkin.workspace.windows_conpty._close_handle", close_handle)
    monkeypatch.setattr("birkin.workspace.windows_conpty._close_pseudo_console", close_pseudo_console)
    monkeypatch.setattr(WindowsJob, "terminate", terminate)
    real_start = threading.Thread.start
    monkeypatch.setattr(threading, "Condition", SignallingCondition)
    monkeypatch.setattr(threading.Thread, "start", defer_start)
    process = conpty.WindowsConPtyProcess(99, 201, 202, 203, 204, WindowsJob(None))
    monkeypatch.setattr(threading.Thread, "start", real_start)
    monkeypatch.setattr(threading, "Condition", threading.Condition.__base__)
    for worker in deferred_threads:
        worker.start()
    assert wait_entered.wait(_TIMEOUT)
    reader = next(worker for worker in deferred_threads if worker.name.startswith("birkin-conpty-reader"))

    def close() -> None:
        process.close(1)
        close_done.set()

    closer = threading.Thread(target=close)
    closer.start()
    try:
        # When real close owns the state transition
        # Then one condition notification releases and joins the reader promptly
        assert close_done.wait(_TIMEOUT)
        assert not reader.is_alive()
        assert reads * abi.BUFFER_SIZE > abi.MAX_BUFFERED_OUTPUT
    finally:
        if not close_done.is_set():
            assert reader_conditions
            with reader_conditions[-1]:
                reader_conditions[-1].notify_all()
            waiter_release.set()
        closer.join(_TIMEOUT)
