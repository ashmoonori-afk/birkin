from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
from collections import Counter
from collections.abc import Generator
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import cast

import psutil
import pytest

from birkin.workspace import windows_conpty as conpty
from birkin.workspace.windows_conpty import (
    WindowsConPtyProcess,
    conpty_supported,
    launch_windows_terminal_process,
)
from tests.windows_conpty_test_support import (
    _CloseCall,
    _is_process_in_job,
    _process_handle_count,
    _top_level_windows_for_pid,
)

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="native Windows ConPTY acceptance",
)

_TIMEOUT_SECONDS = 10.0


def _read_until(
    process: WindowsConPtyProcess,
    marker: bytes,
    max_bytes: int = 16_384,
) -> bytes:
    chunks: list[bytes] = []
    while marker not in (output := b"".join(chunks)):
        chunk = process.read(max_bytes, _TIMEOUT_SECONDS)
        assert chunk
        chunks.append(chunk)
    return output


def _read_eof(process: WindowsConPtyProcess) -> bytes:
    chunks: list[bytes] = []
    while chunk := process.read(16_384, _TIMEOUT_SECONDS):
        chunks.append(chunk)
    return b"".join(chunks)


def _subscribed_read(
    executor: ThreadPoolExecutor,
    process: WindowsConPtyProcess,
    marker: bytes,
    max_bytes: int = 16_384,
) -> Future[bytes]:
    entered = threading.Event()

    def read() -> bytes:
        entered.set()
        return _read_until(process, marker, max_bytes)

    future = executor.submit(read)
    assert entered.wait(_TIMEOUT_SECONDS)
    return future


def _python_bytes_command(data: bytes) -> bytes:
    values = ",".join(str(value) for value in data)
    return (
        f'"{sys.executable}" -c "import sys;sys.stdout.buffer.write(bytes([{values}]))"\r\n'
    ).encode("ascii")


def _launch(tmp_path: Path) -> WindowsConPtyProcess:
    command = Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe"
    return launch_windows_terminal_process(
        command,
        tmp_path,
        dict(os.environ),
        80,
        24,
    )


@pytest.fixture
def terminal(tmp_path: Path) -> Generator[WindowsConPtyProcess]:
    process = _launch(tmp_path)
    try:
        yield process
    finally:
        process.close(1)


def test_conpty_is_supported_when_windows_exports_are_present() -> None:
    # Given this supported native Windows host
    # When capability detection inspects the OS build and exports
    supported = conpty_supported()
    # Then the backend is advertised without launching a process
    assert supported
    assert ctypes.sizeof(conpty.COORD) == 4


@pytest.mark.parametrize("columns,rows", [(0, 24), (1001, 24), (80, 0), (80, 1001)])
def test_launch_rejects_coord_outside_protocol_bounds(
    tmp_path: Path,
    columns: int,
    rows: int,
) -> None:
    # Given an invalid terminal dimension
    command = Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe"
    # When launch parses the COORD boundary, Then no OS resource is acquired
    with pytest.raises(ValueError):
        _ = launch_windows_terminal_process(command, tmp_path, dict(os.environ), columns, rows)


def test_first_create_pipe_failure_closes_pretransfer_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given ten serial launches whose first pipe acquisition fails
    handles_before = _process_handle_count()
    calls = 0

    def fail_first_pipe(*_args: object) -> int:
        nonlocal calls
        calls += 1
        _ = ctypes.set_last_error(5)
        return 0

    monkeypatch.setattr(
        "birkin.workspace._windows_conpty_abi.create_pipe",
        fail_first_pipe,
    )
    # When each launch rolls back before pipe ownership transfer
    for _case in range(10):
        with pytest.raises(OSError, match="CreatePipe"):
            _ = _launch(tmp_path)
        # Then the pre-transfer Job and gate handles leave zero drift
        assert _process_handle_count() == handles_before
    assert calls == 10


def test_launch_creates_start_gated_job_member_without_console(tmp_path: Path) -> None:
    # Given a supported ConPTY host
    # When a terminal process is launched
    process = _launch(tmp_path)
    try:
        # Then it is contained before return and owns no visible console HWND
        assert process.pid > 0
        assert _is_process_in_job(process.pid)
        assert _top_level_windows_for_pid(process.pid) == []
    finally:
        process.close(1)


def test_input_produces_real_output(terminal: WindowsConPtyProcess) -> None:
    # Given a reader subscribed to the exact output condition
    expected = b"CONPTY_OK"
    with ThreadPoolExecutor(max_workers=1) as executor:
        output = _subscribed_read(executor, terminal, expected)
        # When bytes are written to the terminal
        terminal.write(_python_bytes_command(expected), _TIMEOUT_SECONDS)
        # Then the real pseudoconsole publishes those bytes
        assert expected in output.result(_TIMEOUT_SECONDS)


def test_read_preserves_split_utf8_bytes(terminal: WindowsConPtyProcess) -> None:
    # Given one UTF-8 scalar requested one byte at a time
    expected = "한".encode()
    with ThreadPoolExecutor(max_workers=1) as executor:
        output = _subscribed_read(executor, terminal, expected, max_bytes=1)
        # When the shell writes the scalar as raw UTF-8
        terminal.write(_python_bytes_command(expected), _TIMEOUT_SECONDS)
        # Then byte boundaries are lossless for the authority decoder
        assert expected in output.result(_TIMEOUT_SECONDS)


def test_read_preserves_vt_bytes(terminal: WindowsConPtyProcess) -> None:
    # Given a reader subscribed for a semantic SGR reset after ordered text
    expected = b"\x1b[31mRED\x1b[0m"
    entered = threading.Event()

    def read_colored_output() -> bytes:
        chunks: list[bytes] = []
        entered.set()
        while True:
            output = b"".join(chunks)
            colored_at = output.find(b"\x1b[31mRED")
            if colored_at >= 0:
                suffix = output[colored_at + len(b"\x1b[31mRED") :]
                if suffix.startswith((b"\x1b[m", b"\x1b[0m")):
                    return output
            chunk = terminal.read(16_384, _TIMEOUT_SECONDS)
            assert chunk
            chunks.append(chunk)

    with ThreadPoolExecutor(max_workers=1) as executor:
        output = executor.submit(read_colored_output)
        assert entered.wait(_TIMEOUT_SECONDS)
        # When VT bytes traverse ConPTY
        terminal.write(_python_bytes_command(expected), _TIMEOUT_SECONDS)
        # Then controls survive with exact printable content and ordering
        assert b"\x1b[31mRED" in output.result(_TIMEOUT_SECONDS)


def test_resize_accepts_coord_at_protocol_bounds(terminal: WindowsConPtyProcess) -> None:
    # Given a live pseudoconsole
    # When it is resized to the largest accepted COORD
    terminal.resize(1000, 1000)
    # Then the process remains live
    assert terminal.poll() is None


def test_int_writes_etx_to_conpty(terminal: WindowsConPtyProcess) -> None:
    # Given cmd waiting for input with its output reader already live
    # When an interrupt is sent
    terminal.signal("INT")
    # Then the backend remains usable rather than terminating its Job
    assert terminal.poll() is None


def test_int_crosses_write_boundary_as_exact_etx(
    terminal: WindowsConPtyProcess,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a recorder on the ConPTY input write boundary
    writes: list[tuple[bytes, float]] = []

    def record_write(
        _process: WindowsConPtyProcess,
        data: bytes,
        timeout: float,
    ) -> None:
        writes.append((data, timeout))

    monkeypatch.setattr(WindowsConPtyProcess, "write", record_write)
    # When INT is signaled
    terminal.signal("INT")
    # Then exactly one ETX byte crosses the boundary with the bounded timeout
    assert writes == [(b"\x03", 10.0)]


def test_natural_exit_reports_status_after_eof(terminal: WindowsConPtyProcess) -> None:
    # Given an EOF read subscribed before shell exit
    with ThreadPoolExecutor(max_workers=1) as executor:
        eof = executor.submit(_read_eof, terminal)
        # When cmd exits naturally
        terminal.write(b"exit 7\r\n", _TIMEOUT_SECONDS)
        # Then EOF/exit is observable without polling
        _ = eof.result(_TIMEOUT_SECONDS)
        assert terminal.poll() == 7


def test_explicit_close_is_idempotent(terminal: WindowsConPtyProcess) -> None:
    # Given a live process
    # When explicit close is requested twice through one idempotent operation
    terminal.close(23)
    terminal.close(23)
    # Then the retained process status is stable
    assert terminal.poll() == 23


def test_close_reaps_descendant_tree(tmp_path: Path) -> None:
    # Given a terminal whose child identity is reported through output
    process = _launch(tmp_path)
    sentinel = b"BIRKIN_CHILD_PID="
    encoded_sentinel = sentinel.hex()
    script = f"import subprocess,sys,time;p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);marker=bytes.fromhex('{encoded_sentinel}').decode();print(f'{{marker}}{{p.pid}}:READY',flush=True);time.sleep(30)"
    command = subprocess.list2cmdline([sys.executable, "-c", script]).encode() + b"\r\n"
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            pid_output = _subscribed_read(executor, process, sentinel)
            process.write(command, _TIMEOUT_SECONDS)
            output = pid_output.result(_TIMEOUT_SECONDS)
            child_pid = int(output.rsplit(sentinel, 1)[1].split(b":", 1)[0])
        child = psutil.Process(child_pid)
        # When the owning terminal closes
        process.close(31)
        # Then Job containment signals the exact descendant exit
        _ = child.wait(timeout=_TIMEOUT_SECONDS)
        assert not child.is_running()
    finally:
        process.close(31)


def test_create_process_failure_rolls_back_handles_and_threads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given deterministic CreateProcessW failure after ConPTY setup
    handles_before = _process_handle_count()
    threads_before = frozenset(threading.enumerate())

    def fail_create_process(*_args: object) -> int:
        _ = ctypes.set_last_error(5)
        return 0

    monkeypatch.setattr(conpty, "_create_process", fail_create_process)
    # When launch reaches the injected kernel failure
    with pytest.raises(OSError, match="CreateProcessW"):
        _ = _launch(tmp_path)
    # Then rollback leaves no test-owned handle or worker
    assert _process_handle_count() == handles_before
    assert frozenset(threading.enumerate()) == threads_before


def test_close_releases_each_owned_kernel_resource_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given recording wrappers around the two kernel release seams
    real_close_handle = cast(_CloseCall, cast(object, getattr(conpty, "_close_handle")))
    real_close_pseudo_console = cast(
        _CloseCall,
        cast(object, getattr(conpty, "_close_pseudo_console")),
    )
    threads_before = frozenset(threading.enumerate())
    handles: Counter[int] = Counter()
    pseudoconsoles: Counter[int] = Counter()

    def close_handle(handle: int) -> int | None:
        handles[handle] += 1
        return real_close_handle(handle)

    def close_pseudo_console(hpcon: int) -> None:
        pseudoconsoles[hpcon] += 1
        _ = real_close_pseudo_console(hpcon)

    monkeypatch.setattr(conpty, "_close_handle", close_handle)
    monkeypatch.setattr(conpty, "_close_pseudo_console", close_pseudo_console)
    process = _launch(tmp_path)
    handles.clear()
    pseudoconsoles.clear()
    # When close is repeated
    process.close(41)
    process.close(41)
    # Then every observed HANDLE/HPCON closes once and workers join
    assert handles and set(handles.values()) == {1}
    assert pseudoconsoles and set(pseudoconsoles.values()) == {1}
    assert frozenset(threading.enumerate()) == threads_before
    assert process.poll() == 41
