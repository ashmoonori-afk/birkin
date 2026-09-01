from __future__ import annotations

import os
import sys
from pathlib import Path

import pexpect
import pytest

from script.qa.workspace_conpty import ConptySpawn

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
    _ = child.expect(pexpect.EOF)
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

    # When: the caller waits for a pattern that will never arrive.
    with pytest.raises(pexpect.TIMEOUT) as caught:
        _ = child.expect_exact("missing-sentinel", timeout=0.01)

    # Then: the diagnostic identifies both the pattern and trailing buffer.
    diagnostic = str(caught.value)
    assert "missing-sentinel" in diagnostic
    assert "tail-sentinel" in diagnostic
    child.close(force=True)
    _ = child.expect(pexpect.EOF)
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
    _ = child.expect(pexpect.EOF)
    assert not child.isalive()
    assert not child.reader_alive
