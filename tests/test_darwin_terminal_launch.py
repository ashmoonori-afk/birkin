from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

from birkin.config_model import Config
from birkin.workspace.owned_terminal import TerminalAuthority

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="launchd terminal jobs are macOS-specific",
)


def _terminal_labels() -> set[str]:
    listed = subprocess.run(
        ["/bin/launchctl", "list"],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    return {
        fields[-1]
        for line in listed.stdout.splitlines()
        if len(fields := line.split()) == 3
        and fields[-1].startswith("com.birkin.terminal.")
    }


def test_terminal_close_removes_ready_launchd_job(
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
    before = _terminal_labels()
    try:
        _ = terminal.create({
            "actor_kind": "native_human",
            "cwd": str(tmp_path),
        })
        during = _terminal_labels()
        assert len(during - before) == 1
    finally:
        terminal.close_all()
    assert _terminal_labels() == before
