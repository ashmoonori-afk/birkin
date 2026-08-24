"""Native Windows Job Object acceptance for managed shell descendants."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Protocol, cast

import pytest

from birkin.proc import (
    ShellCommand,
    spawn_managed_windows_shell,
    run_shell_command,
    shell_argv,
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


class _Communicate(Protocol):
    def __call__(
        self,
        process: subprocess.Popen[str],
        input: str | None = None,
        timeout: float | None = None,
    ) -> tuple[str | None, str | None]: ...


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
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=shell_env(),
            creationflags=windows_creation_flags(True) | 0x00000004,
        )
        outer.assign(process.pid)
        outer.resume(process.pid)
        stdout, stderr = process.communicate(timeout=20)
        return subprocess.CompletedProcess(
            argv,
            process.returncode,
            stdout,
            stderr,
        )
    finally:
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


def test_real_shell_and_descendant_are_in_intended_job(
    tmp_path: Path,
) -> None:
    from birkin._winjob import WindowsJob

    command = subprocess.list2cmdline(
        [
            sys.executable,
            "-c",
            "import os; print(os.getpid(), flush=True); input()",
        ]
    )
    request = ShellCommand(command, tmp_path, 10, shell_env(), stdin="")
    process, managed = spawn_managed_windows_shell(
        shell_argv(command),
        request,
    )
    assert isinstance(managed, WindowsJob) and process.stdout is not None
    try:
        child_pid = int(f"{process.stdout.readline()}")

        assert str(process.args).casefold().startswith(
            str(shell_argv(command)[0]).casefold()
        )
        assert managed.contains(process.pid)
        assert managed.contains(child_pid)
    finally:
        assert process.stdin is not None
        _ = process.stdin.write("\n")
        process.stdin.flush()
        _ = process.communicate(timeout=10)
        managed.close()


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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_name = f"Local\\BirkinCancel-{os.getpid()}"
    wait_event, close_event, event = _create_named_event(event_name)
    pid_file = tmp_path / "cancel-descendant.pid"
    worker = tmp_path / "cancel-worker.py"
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
    real_communicate = cast(
        _Communicate,
        cast(object, subprocess.Popen.communicate),
    )
    interrupted = False

    def interrupt_first_communicate(
        process: subprocess.Popen[str],
        input: str | None = None,
        timeout: float | None = None,
    ) -> tuple[str, str]:
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            _wait_named_event(wait_event, event)
            raise KeyboardInterrupt
        stdout, stderr = real_communicate(
            process,
            input=input,
            timeout=timeout,
        )
        return stdout or "", stderr or ""

    monkeypatch.setattr(
        subprocess.Popen,
        "communicate",
        interrupt_first_communicate,
    )
    try:
        with pytest.raises(KeyboardInterrupt):
            _ = run_shell_command(
                ShellCommand(
                    command=subprocess.list2cmdline(
                        [sys.executable, str(worker)]
                    ),
                    cwd=tmp_path,
                    timeout=60,
                    environment=shell_env(),
                )
            )
    finally:
        _close_named_event(close_event, event)

    assert interrupted
    child_pid = int(pid_file.read_text(encoding="utf-8"))
    assert _wait_for_process_exit(child_pid)
