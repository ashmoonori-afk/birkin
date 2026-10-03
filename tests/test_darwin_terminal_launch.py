from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

from birkin.config_model import Config
from birkin.workspace.darwin_terminal_process import (
    DarwinTerminalProcess,
    launch_darwin_terminal,
    terminate_darwin_terminal,
)
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
    launched_labels: list[str] = []

    def record_launch(
        *,
        shell_path: str,
        cwd: Path,
        environment: dict[str, str],
        slave_path: str,
        label: str,
    ) -> DarwinTerminalProcess:
        process = launch_darwin_terminal(
            shell_path=shell_path,
            cwd=cwd,
            environment=environment,
            slave_path=slave_path,
            label=label,
        )
        launched_labels.append(process.label)
        return process

    monkeypatch.setattr(
        "birkin.workspace.owned_terminal.launch_darwin_terminal",
        record_launch,
    )
    terminal = TerminalAuthority(
        session_id="session-1",
        workspace_root=tmp_path,
        emit=lambda _event_type, _payload: None,
        config_loader=lambda: cast(Config, {"auto_approve": ["shell"]}),
    )
    other_terminal = TerminalAuthority(
        session_id="session-2",
        workspace_root=tmp_path,
        emit=lambda _event_type, _payload: None,
        config_loader=lambda: cast(Config, {"auto_approve": ["shell"]}),
    )
    try:
        _ = other_terminal.create({
            "actor_kind": "native_human",
            "cwd": str(tmp_path),
        })
        _ = terminal.create({
            "actor_kind": "native_human",
            "cwd": str(tmp_path),
        })
        during = _terminal_labels()
        assert len(launched_labels) == 2
        other_label, owned_label = launched_labels
        assert other_label in during
        assert owned_label in during
        terminal.close_all()
        after = _terminal_labels()
        assert owned_label not in after
        assert other_label in after
    finally:
        terminal.close_all()
        other_terminal.close_all()
    assert not (set(launched_labels) & _terminal_labels())


def test_launchctl_remove_failure_still_terminates_coalition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = DarwinTerminalProcess(
        pid=123,
        label="com.birkin.terminal.cleanup-test",
        coalition_id=456,
    )
    terminated: list[int] = []

    def fail_remove(
        _command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired("/bin/launchctl", 5)

    monkeypatch.setattr(
        subprocess,
        "run",
        fail_remove,
    )
    monkeypatch.setattr(
        "birkin.workspace.darwin_terminal_process.terminate_resource_coalition",
        terminated.append,
    )

    with pytest.raises(subprocess.TimeoutExpired):
        terminate_darwin_terminal(process)

    assert terminated == [456]
