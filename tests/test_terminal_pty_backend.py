from __future__ import annotations

import io
import os
import sys
import threading
from pathlib import Path
from typing import final

import pexpect
import pytest

from script.qa.workspace_conpty import ConptySpawn


@final
class _FakeCancelIo:
    def __init__(self) -> None:
        self.requested = threading.Event()

    def cancel_io(self) -> bool:
        self.requested.set()
        return True


@final
class _DelayedFinalProcess:
    """Controllable mutable process double for final-output ordering."""

    def __init__(self) -> None:
        self.pty = _FakeCancelIo()
        self.pid = 404
        self.exitstatus: int | None = None
        self.read_started = threading.Event()
        self.wait_completed = threading.Event()
        self.allow_final_read = threading.Event()
        self._alive = True
        self._reads = 0

    def read(self, size: int = 1024) -> str:
        _ = size
        self.read_started.set()
        if self._reads == 0:
            if not self.allow_final_read.wait(timeout=1):
                raise OSError("final read was not released")
            self._reads += 1
            return "FINAL-한글-🧵"
        raise OSError("reader drained")

    def write(self, s: str) -> int:
        return len(s)

    def setwinsize(self, rows: int, cols: int) -> None:
        _ = (rows, cols)

    def close(self, force: bool = False) -> None:
        _ = force
        self._alive = False
        self.allow_final_read.set()

    def isalive(self) -> bool:
        return self._alive

    def wait(self) -> int:
        self._alive = False
        self.exitstatus = 0
        self.wait_completed.set()
        return 0

_SENTINEL_CHILD = r"""
import msvcrt
import os
import shutil
import sys

print(f"TTY:{os.isatty(sys.stdin.fileno())}:{os.isatty(sys.stdout.fileno())}", flush=True)
for line in sys.stdin:
    command = line.rstrip("\r\n")
    if command == "size":
        size = shutil.get_terminal_size()
        print(f"SIZE:{size.lines}x{size.columns}", flush=True)
    elif command == "escape":
        character = msvcrt.getwch()
        print(f"ESC:{ord(character)}", flush=True)
    elif command == "quit":
        print("DONE", flush=True)
        raise SystemExit(0)
    else:
        print(f"ECHO:{command}", flush=True)
"""


def _spawn(tmp_path: Path) -> ConptySpawn:
    return ConptySpawn.spawn(
        sys.executable,
        ["-u", "-c", _SENTINEL_CHILD],
        cwd=tmp_path,
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        encoding="utf-8",
        timeout=3,
        dimensions=(30, 100),
    )


def test_reader_drains_final_output_after_wait_and_honors_log_reassignment() -> None:
    # Given: process wait completes while its final terminal read is delayed.
    process = _DelayedFinalProcess()
    child = ConptySpawn(process, encoding="utf-8", timeout=1)
    first_log = io.StringIO()
    final_log = io.StringIO()
    child.set_logfile_read(first_log)
    assert process.read_started.wait(timeout=1)
    assert process.wait_completed.wait(timeout=1)

    # When: the consumer reassigns the log before releasing the final read.
    child.set_logfile_read(final_log)
    process.allow_final_read.set()
    _ = child.expect_exact("FINAL-한글-🧵")
    child.expect_eof()
    child.close()

    # Then: EOF follows the final chunk and only the active log receives it.
    assert "FINAL-한글-🧵" not in first_log.getvalue()
    assert "FINAL-한글-🧵" in final_log.getvalue()
    assert not child.reader_alive


@pytest.mark.skipif(sys.platform != "win32", reason="native ConPTY required")
def test_conpty_round_trips_tty_unicode_resize_escape_and_clean_eof(
    tmp_path: Path,
) -> None:
    # Given: a native Windows pseudo-terminal child.
    child = _spawn(tmp_path)

    # When: the caller exchanges Unicode, resizes, sends ESC, and quits.
    _ = child.expect_exact("TTY:True:True")
    _ = child.send("한글-🧵\r")
    _ = child.expect_exact("ECHO:한글-🧵")
    child.setwinsize(24, 60)
    _ = child.send("size\r")
    _ = child.expect_exact("SIZE:24x60")
    _ = child.send("escape\r")
    _ = child.send("\x1b")
    _ = child.expect_exact("ESC:27")
    _ = child.send("quit\r")
    _ = child.expect_exact("DONE")
    child.expect_eof()
    child.close()

    # Then: the exact child and its reader both exited successfully.
    assert child.exitstatus == 0
    assert not child.isalive()
    assert not child.reader_alive


@pytest.mark.skipif(sys.platform != "win32", reason="native ConPTY required")
def test_conpty_timeout_names_pattern_and_trailing_buffer(tmp_path: Path) -> None:
    # Given: a live ConPTY child with known trailing output.
    child = _spawn(tmp_path)
    _ = child.expect_exact("TTY:True:True")
    _ = child.send("tail-sentinel\r")
    _ = child.expect_exact("ECHO:")

    # When: the caller waits for a pattern that will never arrive.
    with pytest.raises(pexpect.TIMEOUT) as caught:
        _ = child.expect_exact("missing-sentinel", timeout=0.01)

    # Then: the diagnostic identifies both the pattern and trailing buffer.
    diagnostic = str(caught.value)
    assert "missing-sentinel" in diagnostic
    assert "tail-sentinel" in diagnostic
    child.close(force=True)
    child.expect_eof()
    assert not child.isalive()
    assert not child.reader_alive


@pytest.mark.skipif(sys.platform != "win32", reason="native ConPTY required")
def test_conpty_termination_yields_eof_without_reader_leak(tmp_path: Path) -> None:
    # Given: a native child blocked waiting for terminal input.
    child = _spawn(tmp_path)
    _ = child.expect_exact("TTY:True:True")

    # When: the owner terminates the exact child handle.
    child.close(force=True)

    # Then: EOF is observable and no child or reader remains live.
    child.expect_eof()
    assert not child.isalive()
    assert not child.reader_alive
