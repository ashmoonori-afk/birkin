"""PowerShell requires a deliberate operator decision.

The gate is a conservative literal-name check on the raw command, so cmd
wrappers (FOR/IF bodies, ``@``, grouping, nesting) can no longer smuggle an
interpreter past the opt-in contract. A wrapper, an unquoted name, or a
quoted bare name all queue the exact operation instead of running.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast, final

import pytest

from birkin import approval_execution, approvals, config, store
from birkin.proc import ShellCommand
from birkin.tools import ToolContext, build_registry
from birkin.tools import shell as shell_mod

# The wrapper shapes the pre-fix matcher failed to recognize: FOR/IF bodies,
# `@`, grouping, nesting, adjacent separators, and nested quoted invocations.
WRAPPER_COMMANDS = [
    "for %i in (x) do @powershell -NoProfile -Command Write-Output AUDIT_PROBE",
    "if 1==1 @pwsh.exe -NoProfile -Command Write-Output AUDIT_PROBE",
    'cmd /c "for %i in (x) do @powershell -NoProfile -Command Write-Output AUDIT_PROBE"',
    "for %i in (x) do @powershell&echo AUDIT_PROBE",
    "if 1==1 (pwsh.exe)",
    'cmd /c "(powershell)"',
    "@PoWeRsHeLl.ExE|echo AUDIT_PROBE",
    "(pwsh)>audit.txt",
    "@powershell<input.txt",
    "call @powershell.exe -NoProfile -Command Write-Output AUDIT_PROBE",
    (
        'start "" /wait "C:\\Program Files\\PowerShell\\7\\pwsh.exe" '
        "-NoProfile -Command Write-Output AUDIT_PROBE"
    ),
    'cmd /d /s /c "(pwsh.exe)"',
    "C:powershell.exe -NoProfile -Command Write-Output AUDIT_PROBE",
]

# The three examples that also escaped PR #104's matcher.
PR104_REJECTION_COMMANDS = [
    "for %i in (x) do @powershell&echo AUDIT_PROBE",
    "if 1==1 (pwsh.exe)",
    'cmd /c "(powershell)"',
]

# Invocations terminated by a trailing boundary character that no integration
# case above already covers.
TRAILING_BOUNDARY_COMMANDS = [
    "echo hi\tpwsh",
    "echo pwsh\n",
    "echo x\npwsh.exe",
    'echo hi"powershell"',
    "echo hi'pwsh.exe'",
    "echo hi(powershell",
    "(powershell)",
    "echo hi,powershell",
    "echo hi|powershell",
    "echo hi<powershell",
    "echo hi>powershell",
    "echo hi=powershell",
    "echo hi>(pwsh.exe)",
]

# Data-only commands that obviously contain no PowerShell invocation. The
# detector is literal, so it must leave these alone.
COMPATIBILITY_COMMANDS = [
    "echo powershell_notes.txt",
    "echo mypwsh.exe",
    "echo powershell.exe.bak",
    "echo pwsh-preview",
    "echo C:\\tools\\mypowershell.exe",
    "echo C:\\tools\\powershell\\notes.txt",
    "echo pwsh/custom-tool",
    "echo powershell.exe_extra",
    "echo ordinary-output",
]

# Conservative positives: the literal name appears as a standalone token, so
# the gate applies even though nothing is executed. Explicit opt-in and
# one-shot approval remain usable.
CONSERVATIVE_POSITIVE_COMMANDS = [
    "echo powershell",
    'echo "pwsh.exe"',
    "echo hi;powershell",
]

WRAPPER_AND_POSITIVE_COMMANDS = WRAPPER_COMMANDS + CONSERVATIVE_POSITIVE_COMMANDS

NO_INVOCATION_COMMANDS = COMPATIBILITY_COMMANDS + ["echo cycle"]

SEPARATOR_TERMINATED_COMMANDS = [
    "echo hi;powershell",
    "echo hi&powershell",
    "echo hi|powershell",
]

HARDLINE_COMMAND = "rm -rf /"


@final
class _Completed:
    returncode: int = 0
    stdout: str = "powershell ran"
    stderr: str = ""


class _Runner:
    """Records executed commands so a blocked command proves zero calls."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, request: ShellCommand) -> _Completed:
        self.calls.append(request.command)
        return _Completed()


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))


def _registry(tmp_path: Path, cfg: dict[str, object]):
    return build_registry(
        ToolContext(cfg=cfg, client=None, cwd=tmp_path),
        include={"shell"},
    )


def _mock_runner(monkeypatch: pytest.MonkeyPatch) -> _Runner:
    runner = _Runner()
    monkeypatch.setattr(shell_mod, "run_shell_command", runner)
    return runner


def _record_operation(record: dict[str, object]) -> dict[str, object]:
    payload_value = record["payload"]
    assert isinstance(payload_value, dict)
    payload = cast(dict[str, object], payload_value)
    operation_value = payload["operation"]
    assert isinstance(operation_value, dict)
    return cast(dict[str, object], operation_value)


def _operation_command(operation: dict[str, object]) -> str:
    tool_input_value = operation["input"]
    assert isinstance(tool_input_value, dict)
    tool_input = cast(dict[str, object], tool_input_value)
    command = tool_input["command"]
    assert isinstance(command, str)
    return command


def _operation_cwd(operation: dict[str, object]) -> str:
    cwd = operation["cwd"]
    assert isinstance(cwd, str)
    return cwd


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
    runner = _mock_runner(monkeypatch)
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
    assert runner.calls == []
    assert len(pending) == 1
    record: dict[str, object] = pending[0]
    assert record["category"] == "operation"


@pytest.mark.parametrize("opt_in", [None, False, "true"])
@pytest.mark.parametrize("command", WRAPPER_AND_POSITIVE_COMMANDS)
def test_wrappers_require_powershell_opt_in(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    opt_in: object,
) -> None:
    runner = _mock_runner(monkeypatch)
    cfg: dict[str, object] = {
        "shell_approval": "off",
        "auto_approve": ["shell"],
    }
    if opt_in is not None:
        cfg["allow_powershell"] = opt_in
    registry = _registry(tmp_path, cfg)

    result = registry.execute("run_shell", {"command": command})
    repeated = registry.execute("run_shell", {"command": command})

    pending = store.list_pending()
    assert result.is_error
    assert repeated.is_error
    assert runner.calls == []
    assert len(pending) == 1
    operation = _record_operation(pending[0])
    assert operation["gate"] == "powershell_opt_in"
    assert operation["tool"] == "run_shell"
    assert _operation_command(operation) == command
    assert _operation_cwd(operation) == str(tmp_path.resolve())


@pytest.mark.parametrize("command", WRAPPER_AND_POSITIVE_COMMANDS)
def test_wrappers_run_once_with_explicit_opt_in(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    runner = _mock_runner(monkeypatch)
    registry = _registry(
        tmp_path,
        {
            "allow_powershell": True,
            "shell_approval": "off",
        },
    )

    result = registry.execute("run_shell", {"command": command})

    assert result.is_error is False
    assert runner.calls == [command]
    assert store.list_pending() == []


@pytest.mark.parametrize("command", SEPARATOR_TERMINATED_COMMANDS)
def test_separator_terminated_invocation_queues_one_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    runner = _mock_runner(monkeypatch)
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
    assert runner.calls == []
    assert len(pending) == 1
    operation = _record_operation(pending[0])
    assert operation["gate"] == "powershell_opt_in"
    assert operation["tool"] == "run_shell"
    assert _operation_command(operation) == command
    assert _operation_cwd(operation) == str(tmp_path.resolve())


@pytest.mark.parametrize("command", COMPATIBILITY_COMMANDS)
def test_non_powershell_names_execute_without_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    runner = _mock_runner(monkeypatch)
    registry = _registry(tmp_path, {"shell_approval": "off"})

    result = registry.execute("run_shell", {"command": command})

    assert result.is_error is False
    assert runner.calls == [command]
    assert store.list_pending() == []


def test_hardline_refusal_wins_over_powershell_opt_in(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _mock_runner(monkeypatch)
    registry = _registry(
        tmp_path,
        {
            "allow_powershell": True,
            "shell_approval": "off",
        },
    )

    result = registry.execute("run_shell", {"command": HARDLINE_COMMAND})

    assert result.is_error
    assert runner.calls == []
    assert store.list_pending() == []


def test_powershell_config_opt_in_allows_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _mock_runner(monkeypatch)
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
    assert runner.calls == ["powershell -NoProfile -Command Get-Date"]


def test_trailing_boundary_matcher_accepts_adjacent_separators() -> None:
    pattern = shell_mod._POWERSHELL_SEGMENT  # pyright: ignore[reportPrivateUsage]
    for command in TRAILING_BOUNDARY_COMMANDS:
        assert pattern.search(command), command


def test_matcher_still_rejects_continued_filenames() -> None:
    pattern = shell_mod._POWERSHELL_SEGMENT  # pyright: ignore[reportPrivateUsage]
    for command in COMPATIBILITY_COMMANDS:
        assert not pattern.search(command), command


def test_manual_approval_runs_exact_powershell_command_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _mock_runner(monkeypatch)
    registry = _registry(tmp_path, {"shell_approval": "off"})
    command = "powershell -NoProfile -Command Get-Date"
    blocked = registry.execute("run_shell", {"command": command})
    record: dict[str, object] = store.list_pending()[0]
    raw_id: object = record["id"]
    assert isinstance(raw_id, str)
    approval_id = raw_id

    resolution = approval_execution.approve(
        approval_id,
        approvals.execute_action,
        approved_by="human:test",
        approved_via="test",
    )

    assert blocked.is_error
    assert resolution["ok"] is True, resolution
    assert runner.calls == [command]


@pytest.mark.parametrize("command", WRAPPER_COMMANDS)
def test_wrapper_approval_runs_exact_command_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    runner = _mock_runner(monkeypatch)
    registry = _registry(tmp_path, {"shell_approval": "off"})

    blocked = registry.execute("run_shell", {"command": command})
    pending = store.list_pending()
    assert blocked.is_error
    assert runner.calls == []
    assert len(pending) == 1
    record: dict[str, object] = pending[0]
    raw_id: object = record["id"]
    assert isinstance(raw_id, str)
    approval_id = raw_id

    resolution = approval_execution.approve(
        approval_id,
        approvals.execute_action,
        approved_by="human:test",
        approved_via="test",
    )
    assert resolution["ok"] is True, resolution
    assert runner.calls == [command]

    again = approval_execution.approve(
        approval_id,
        approvals.execute_action,
        approved_by="human:test",
        approved_via="test",
    )
    assert again["ok"] is False
    assert runner.calls == [command]


def test_wrapper_approval_binds_the_exact_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _mock_runner(monkeypatch)
    registry = _registry(tmp_path, {"shell_approval": "off"})
    first = WRAPPER_COMMANDS[0]
    second = WRAPPER_COMMANDS[0].replace("AUDIT_PROBE", "SECOND_PROBE")

    _ = registry.execute("run_shell", {"command": first})
    first_record: dict[str, object] = store.list_pending()[0]
    raw_first_id: object = first_record["id"]
    assert isinstance(raw_first_id, str)
    first_id = raw_first_id
    assert approval_execution.approve(
        first_id,
        approvals.execute_action,
        approved_by="human:test",
        approved_via="test",
    )["ok"] is True

    _ = registry.execute("run_shell", {"command": second})
    pending = store.list_pending()
    assert len(pending) == 1
    assert pending[0]["id"] != first_id
    assert _operation_command(_record_operation(pending[0])) == second
    assert runner.calls == [first]


def test_matcher_rejects_non_invocations() -> None:
    pattern = shell_mod._POWERSHELL_SEGMENT  # pyright: ignore[reportPrivateUsage]
    for command in NO_INVOCATION_COMMANDS:
        assert not pattern.search(command), command
