from __future__ import annotations

import os
import select
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

from birkin.config_model import Config
from birkin.workspace.owned_terminal import TerminalAuthority

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="Darwin terminal signal isolation is macOS-specific",
)


def test_shell_cannot_signal_external_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    terminal = TerminalAuthority(
        session_id="session-1",
        workspace_root=tmp_path,
        emit=lambda _event_type, _payload: None,
        config_loader=lambda: cast(Config, {"auto_approve": ["shell"]}),
    )
    status_path = tmp_path / "signal-status"
    os.mkfifo(status_path, mode=0o600)
    status_fd = os.open(status_path, os.O_RDWR | os.O_NONBLOCK)
    victim = subprocess.Popen(["/bin/sleep", "30"])
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
                f"kill -9 {victim.pid}; "
                f"printf '%s' $? > {status_path}\n"
            ),
        })
        readable, _, _ = select.select([status_fd], [], [], 5)
        assert readable == [status_fd]
        assert os.read(status_fd, 8) != b"0"
        assert victim.poll() is None
    finally:
        terminal.close_all()
        victim.kill()
        _ = victim.wait(timeout=5)
        os.close(status_fd)
