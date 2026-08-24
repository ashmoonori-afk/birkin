from __future__ import annotations

import os
import plistlib
import select
import signal
import socket
import subprocess
import sys
from pathlib import Path
from typing import cast

import psutil
import pytest

from birkin.config_model import Config
from birkin.workspace.owned_terminal import TerminalAuthority

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="Darwin resource coalitions are macOS-specific",
)


def _authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> TerminalAuthority:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    return TerminalAuthority(
        session_id="session-1",
        workspace_root=tmp_path,
        emit=lambda _event_type, _payload: None,
        config_loader=lambda: cast(Config, {"auto_approve": ["shell"]}),
    )


def test_close_reaps_double_forked_setsid_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminal = _authority(tmp_path, monkeypatch)
    ready_path = tmp_path / "child-ready"
    os.mkfifo(ready_path, mode=0o600)
    ready_fd = os.open(ready_path, os.O_RDWR | os.O_NONBLOCK)
    child_pid = 0
    try:
        opened = terminal.create({
            "actor_kind": "native_human",
            "cwd": str(tmp_path),
        })
        child_code = (
            "import os,time;"
            "child=os.fork();"
            "child and os._exit(0);"
            "os.setsid();"
            f"f=open({str(ready_path)!r},'w');"
            "f.write(str(os.getpid()));f.close();"
            "time.sleep(30)"
        )
        _ = terminal.input({
            "terminal_id": opened["terminal_id"],
            "lease": opened["lease"],
            "sequence": 1,
            "data": (
                f"nohup python3 -c {child_code!r} "
                "</dev/null >/dev/null 2>&1 &\n"
            ),
        })
        readable, _, _ = select.select([ready_fd], [], [], 5)
        assert readable == [ready_fd]
        child_pid = int(os.read(ready_fd, 32))
        assert os.getpgid(child_pid) == child_pid
        assert os.getsid(child_pid) == child_pid

        child = psutil.Process(child_pid)
        assert child.ppid() == 1
        terminal.close_all()

        _ = child.wait(timeout=5)
        assert not child.is_running()
    finally:
        terminal.close_all()
        os.close(ready_fd)
        if child_pid:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_shell_cannot_submit_escape_coalition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminal = _authority(tmp_path, monkeypatch)
    status_path = tmp_path / "launchctl-status"
    os.mkfifo(status_path, mode=0o600)
    status_fd = os.open(status_path, os.O_RDWR | os.O_NONBLOCK)
    label = f"com.birkin.escape-test.{os.getpid()}"
    try:
        opened = terminal.create({
            "actor_kind": "native_human",
            "cwd": str(tmp_path),
        })
        _ = terminal.input({
            "terminal_id": opened["terminal_id"],
            "lease": opened["lease"],
            "sequence": 1,
            "data": (
                f"/bin/launchctl submit -l {label} -- /bin/sleep 30; "
                f"printf '%s' $? > {status_path}\n"
            ),
        })
        readable, _, _ = select.select([status_fd], [], [], 5)
        assert readable == [status_fd]
        assert os.read(status_fd, 8) != b"0"

        listed = subprocess.run(
            ["/bin/launchctl", "list", label],
            capture_output=True,
            timeout=5,
            check=False,
        )
        assert listed.returncode != 0
    finally:
        _ = subprocess.run(
            ["/bin/launchctl", "remove", label],
            capture_output=True,
            timeout=5,
            check=False,
        )
        terminal.close_all()
        os.close(status_fd)


def test_shell_cannot_launch_escape_application(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminal = _authority(tmp_path, monkeypatch)
    app_ready_path = tmp_path / "app-ready"
    os.mkfifo(app_ready_path, mode=0o600)
    app_ready_fd = os.open(app_ready_path, os.O_RDWR | os.O_NONBLOCK)
    app_root = tmp_path / "Escape.app"
    executable = app_root / "Contents" / "MacOS" / "Escape"
    executable.parent.mkdir(parents=True)
    script = (
        "#!/bin/sh\n"
        + f"printf '%s' $$ > {app_ready_path}\n"
        + "exec /bin/sleep 30\n"
    )
    _ = executable.write_text(
        script,
        encoding="utf-8",
    )
    executable.chmod(0o700)
    with (app_root / "Contents" / "Info.plist").open("wb") as stream:
        plistlib.dump({
            "CFBundleExecutable": "Escape",
            "CFBundleIdentifier": f"com.birkin.escape-test.{os.getpid()}",
            "CFBundlePackageType": "APPL",
        }, stream)
    escape_pid = 0
    try:
        opened = terminal.create({
            "actor_kind": "native_human",
            "cwd": str(tmp_path),
        })
        _ = terminal.input({
            "terminal_id": opened["terminal_id"],
            "lease": opened["lease"],
            "sequence": 1,
            "data": (
                f"/usr/bin/open -n {app_root} "
                ">/dev/null 2>&1 &\n"
            ),
        })
        app_ready, _, _ = select.select([app_ready_fd], [], [], 3)
        if app_ready:
            escape_pid = int(os.read(app_ready_fd, 32))
        assert app_ready == []
        assert escape_pid == 0
    finally:
        terminal.close_all()
        os.close(app_ready_fd)
        if escape_pid:
            try:
                os.kill(escape_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_shell_cannot_connect_existing_process_broker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminal = _authority(tmp_path, monkeypatch)
    broker_path = Path(f"/private/tmp/bk-broker-{os.getpid()}.sock")
    status_path = tmp_path / "broker-status"
    os.mkfifo(status_path, mode=0o600)
    status_fd = os.open(status_path, os.O_RDWR | os.O_NONBLOCK)
    broker = socket.socket(socket.AF_UNIX)
    broker.bind(str(broker_path))
    broker.listen()
    broker.setblocking(False)
    try:
        opened = terminal.create({
            "actor_kind": "native_human",
            "cwd": str(tmp_path),
        })
        client_code = (
            "import socket;"
            "client=socket.socket(socket.AF_UNIX);"
            f"client.connect({str(broker_path)!r})"
        )
        _ = terminal.input({
            "terminal_id": opened["terminal_id"],
            "lease": opened["lease"],
            "sequence": 1,
            "data": (
                f"python3 -c {client_code!r}; "
                f"printf '%s' $? > {status_path}\n"
            ),
        })
        readable, _, _ = select.select([status_fd], [], [], 5)
        assert readable == [status_fd]
        assert os.read(status_fd, 8) != b"0"
        with pytest.raises(BlockingIOError):
            _ = broker.accept()
    finally:
        terminal.close_all()
        broker.close()
        os.close(status_fd)
        broker_path.unlink(missing_ok=True)
