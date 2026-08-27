"""PowerShell requires a deliberate operator decision."""

from __future__ import annotations

from pathlib import Path
from typing import final

import pytest

from birkin import approvals, config, store
from birkin.proc import ShellCommand
from birkin.tools import ToolContext, build_registry
from birkin.tools import shell as shell_mod


@final
class _Completed:
    returncode: int = 0
    stdout: str = "powershell ran"
    stderr: str = ""


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))


def _registry(tmp_path: Path, cfg: dict[str, object]):
    return build_registry(
        ToolContext(cfg=cfg, client=None, cwd=tmp_path),
        include={"shell"},
    )


def test_powershell_is_disabled_by_default() -> None:
    assert config.DEFAULT_CONFIG["allow_powershell"] is False


@pytest.mark.parametrize(
    "command",
    [
        "powershell -NoProfile -Command Get-Date",
        "pwsh.exe -NoProfile -Command Get-Date",
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe Get-Date",
        "cmd /c powershell -NoProfile -Command Get-Date",
    ],
)
def test_powershell_queues_even_when_shell_auto_approval_is_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    calls: list[str] = []

    def run(request: ShellCommand) -> _Completed:
        calls.append(request.command)
        return _Completed()

    monkeypatch.setattr(
        shell_mod,
        "run_shell_command",
        run,
    )
    registry = _registry(
        tmp_path,
        {
            "shell_approval": "off",
            "auto_approve": ["shell"],
        },
    )

    result = registry.execute("run_shell", {"command": command})

    pending = store.list_pending()
    assert result.is_error
    assert calls == []
    assert len(pending) == 1
    record: dict[str, object] = pending[0]
    assert record["category"] == "operation"


def test_powershell_config_opt_in_allows_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def run(request: ShellCommand) -> _Completed:
        calls.append(request.command)
        return _Completed()

    monkeypatch.setattr(
        shell_mod,
        "run_shell_command",
        run,
    )
    registry = _registry(
        tmp_path,
        {
            "allow_powershell": True,
            "shell_approval": "off",
        },
    )

    result = registry.execute(
        "run_shell",
        {"command": "powershell -NoProfile -Command Get-Date"},
    )

    assert result.is_error is False
    assert calls == ["powershell -NoProfile -Command Get-Date"]


def test_manual_approval_runs_exact_powershell_command_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def run(request: ShellCommand) -> _Completed:
        calls.append(request.command)
        return _Completed()

    monkeypatch.setattr(
        shell_mod,
        "run_shell_command",
        run,
    )
    registry = _registry(tmp_path, {"shell_approval": "off"})
    command = "powershell -NoProfile -Command Get-Date"
    blocked = registry.execute("run_shell", {"command": command})
    record: dict[str, object] = store.list_pending()[0]
    approval_id = record["id"]
    assert isinstance(approval_id, str)

    resolution = approvals.approve(approval_id, approved_by="human:test", approved_via="test")

    assert blocked.is_error
    assert resolution["ok"] is True, resolution
    assert calls == [command]
