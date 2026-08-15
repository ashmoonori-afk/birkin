"""Native Windows Job Object acceptance for managed shell descendants."""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Protocol, cast

import pytest

from birkin.proc import (
    ShellCommand,
    run_shell_command,
    shell_env,
    windows_creation_flags,
)

pytestmark = pytest.mark.skipif(
    os.name != "nt",
    reason="native Windows Job Object acceptance",
)


class _WinCall(Protocol):
    argtypes: list[object]
    restype: object

    def __call__(self, *args: object) -> int: ...


def _wait_for_process_exit(pid: int, timeout_ms: int = 5_000) -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = cast(_WinCall, cast(object, kernel32.OpenProcess))
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    wait = cast(_WinCall, cast(object, kernel32.WaitForSingleObject))
    wait.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    wait.restype = wintypes.DWORD
    close = cast(_WinCall, cast(object, kernel32.CloseHandle))
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    handle = open_process(0x00100000, False, pid)
    if not handle:
        return True
    try:
        return wait(handle, timeout_ms) == 0
    finally:
        _ = close(handle)


def _create_named_event(
    name: str,
) -> tuple[_WinCall, _WinCall, int]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create = cast(_WinCall, cast(object, kernel32.CreateEventW))
    create.argtypes = [
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    create.restype = wintypes.HANDLE
    handle = create(None, True, False, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    wait = cast(_WinCall, cast(object, kernel32.WaitForSingleObject))
    wait.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    wait.restype = wintypes.DWORD
    close = cast(_WinCall, cast(object, kernel32.CloseHandle))
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    return wait, close, handle


def _wait_named_event(wait: _WinCall, handle: int) -> None:
    assert wait(handle, 10_000) == 0


def _close_named_event(close: _WinCall, handle: int) -> None:
    assert close(handle)


def _write(path: Path, source: str) -> None:
    _ = path.write_text(source, encoding="utf-8")


def _source(*lines: str) -> str:
    return "\n".join((*lines, ""))


def _run_driver_in_outer_job(
    argv: list[str],
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    from birkin import _winjob

    outer = _winjob.WindowsJob.create()
    gate = _winjob.WindowsStartGate.create()
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            gate.bootstrap_argv(argv),
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=shell_env(),
            creationflags=windows_creation_flags(True),
        )
        outer.assign(process.pid)
        gate.release()
        stdout, stderr = process.communicate(timeout=20)
        return subprocess.CompletedProcess(
            argv,
            process.returncode,
            stdout,
            stderr,
        )
    finally:
        gate.close()
        outer.close()
        if process is not None and process.poll() is None:
            process.kill()
            _ = process.wait(timeout=10)


def test_successful_shell_cannot_leak_background_child(
    tmp_path: Path,
) -> None:
    pid_file = tmp_path / "background.pid"
    parent = tmp_path / "background-parent.py"
    _ = parent.write_text(
        "import os, subprocess, sys\n"
        + "from pathlib import Path\n"
        + "with open(os.devnull, 'r+b') as null:\n"
        + "    child = subprocess.Popen([\n"
        + "        sys.executable, '-c', 'import time; time.sleep(30)'\n"
        + "    ], stdin=null, stdout=null, stderr=null)\n"
        + f"Path({str(pid_file)!r}).write_text(str(child.pid), encoding='utf-8')\n",
        encoding="utf-8",
    )
    command = subprocess.list2cmdline([sys.executable, str(parent)])

    result = run_shell_command(
        ShellCommand(
            command=command,
            cwd=tmp_path,
            timeout=10,
            environment=shell_env(),
        )
    )
    child_pid = int(pid_file.read_text(encoding="utf-8"))

    assert result.returncode == 0
    assert _wait_for_process_exit(child_pid)


def test_bootstrap_starts_isolated_before_gate_release() -> None:
    from birkin import _winjob

    gate = _winjob.WindowsStartGate.create()
    try:
        argv = gate.bootstrap_argv(["cmd.exe", "/d", "/c", "echo ok"])
    finally:
        gate.close()

    assert argv[0] == sys.executable
    assert argv[1:3] == ["-I", "-S"]
    assert Path(argv[3]).name == "_winjob_bootstrap.py"
    assert argv[4].startswith("Local\\BirkinJob-")
    assert argv[4].endswith("-release")
    assert argv[5].startswith("Local\\BirkinJob-")
    assert argv[5].endswith("-ready")


def test_job_object_ctypes_layout_matches_winnt() -> None:
    from birkin import _winjob

    assert _winjob.job_layout_sizes() == (48, 64, 144)


def test_managed_shell_runs_inside_existing_outer_job(
    tmp_path: Path,
) -> None:
    driver = tmp_path / "nested-job-driver.py"
    _write(
        driver,
        _source(
            "import subprocess, sys",
            "from pathlib import Path",
            "from birkin.proc import ShellCommand, run_shell_command, shell_env",
            "command = subprocess.list2cmdline([",
            "    sys.executable, '-c', \"print('nested-job-ok')\"",
            "])",
            "result = run_shell_command(ShellCommand(",
            "    command=command, cwd=Path.cwd(), timeout=10,",
            "    environment=shell_env(),",
            "))",
            "print(result.stdout, end='')",
            "raise SystemExit(result.returncode)",
        ),
    )

    result = _run_driver_in_outer_job(
        [sys.executable, str(driver)],
        tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "nested-job-ok\n"


def test_ctrl_break_cancels_owned_descendant_tree(
    tmp_path: Path,
) -> None:
    event_name = f"Local\\BirkinCancel-{os.getpid()}"
    wait_event, close_event, event = _create_named_event(event_name)
    pid_file = tmp_path / "cancel-descendant.pid"
    worker = tmp_path / "cancel-worker.py"
    driver = tmp_path / "cancel-driver.py"
    _write(
        worker,
        _source(
            "import ctypes, subprocess, sys, time",
            "from ctypes import wintypes",
            "from pathlib import Path",
            "child = subprocess.Popen([",
            "    sys.executable, '-c', 'import time; time.sleep(30)'",
            "])",
            f"Path({str(pid_file)!r}).write_text(",
            "    str(child.pid), encoding='utf-8'",
            ")",
            "kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)",
            "open_event = kernel32.OpenEventW",
            "open_event.argtypes = [",
            "    wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR",
            "]",
            "open_event.restype = wintypes.HANDLE",
            f"event = open_event(0x0002, False, {event_name!r})",
            "if not event or not kernel32.SetEvent(event):",
            "    raise SystemExit(125)",
            "kernel32.CloseHandle(event)",
            "time.sleep(30)",
        ),
    )
    _write(
        driver,
        _source(
            "import signal, subprocess, sys",
            "from pathlib import Path",
            "from birkin.proc import ShellCommand, run_shell_command, shell_env",
            f"command = subprocess.list2cmdline([sys.executable, {str(worker)!r}])",
            "signal.signal(signal.SIGBREAK, signal.default_int_handler)",
            "try:",
            "    run_shell_command(ShellCommand(",
            "        command=command, cwd=Path.cwd(), timeout=60,",
            "        environment=shell_env(),",
            "    ))",
            "except KeyboardInterrupt:",
            "    raise SystemExit(130)",
        ),
    )
    process = subprocess.Popen(
        [sys.executable, str(driver)],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=shell_env(),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    try:
        _wait_named_event(wait_event, event)
        child_pid = int(pid_file.read_text(encoding="utf-8"))
        process.send_signal(signal.CTRL_BREAK_EVENT)
        stdout, stderr = process.communicate(timeout=15)
    finally:
        _close_named_event(close_event, event)
        if process.poll() is None:
            process.kill()
            _ = process.wait(timeout=10)

    assert process.returncode == 130, (stdout, stderr)
    assert _wait_for_process_exit(child_pid)
