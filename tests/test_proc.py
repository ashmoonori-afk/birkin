import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from birkin import proc


def _command(parts: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(parts)
    return shlex.join(parts)


class _FakeProcess:
    pid = 4312

    def __init__(self) -> None:
        self.killed = False

    def kill(self) -> None:
        self.killed = True


class _InterruptedProcess(_FakeProcess):
    def __init__(self) -> None:
        super().__init__()
        self.communications = 0

    def communicate(self, **_kwargs):
        self.communications += 1
        if self.communications == 1:
            raise KeyboardInterrupt
        return "", ""

    def wait(self) -> int:
        return 0


class _ManagedTree:
    def __init__(self) -> None:
        self.terminations: list[int] = []
        self.closed = False

    def terminate(self, exit_code: int = 1) -> None:
        self.terminations.append(exit_code)

    def close(self) -> None:
        self.closed = True


class _ScriptedWindowsShell:
    """Mutable deterministic process script for Windows retry tests."""

    def __init__(
        self,
        outcomes: list[tuple[int, str, str]],
        advance: Callable[[], None] | None = None,
    ) -> None:
        self.outcomes = outcomes
        self.advance = advance
        self.attempts: list[tuple[str, proc.ShellCommand]] = []
        self.timeouts: list[float] = []

    def __call__(self, argv, request):
        command = argv[-1].split(" & ", 1)[-1]
        self.attempts.append((command, request))
        outcome = self.outcomes[len(self.attempts) - 1]
        return _ScriptedProcess(self, outcome), _ManagedTree()


class _ScriptedProcess(_FakeProcess):
    def __init__(
        self,
        script: _ScriptedWindowsShell,
        outcome: tuple[int, str, str],
    ) -> None:
        super().__init__()
        self.script = script
        self.returncode, self.stdout, self.stderr = outcome

    def communicate(self, **kwargs):
        self.script.timeouts.append(kwargs["timeout"])
        if self.script.advance is not None:
            self.script.advance()
        return self.stdout, self.stderr

    def wait(self) -> int:
        return self.returncode


def _native_request(
    command: str,
    tmp_path: Path,
    *,
    timeout: int = 30,
) -> proc.ShellCommand:
    return proc.ShellCommand(
        command=command,
        cwd=tmp_path,
        timeout=timeout,
        environment=dict(os.environ),
    )


def test_popen_tree_kwargs_is_native() -> None:
    expected = (
        {"creationflags": proc.subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    assert proc.popen_tree_kwargs() == expected


def test_kill_tree_terminates_posix_process_group(monkeypatch) -> None:
    process = _FakeProcess()
    calls: list[tuple[int, signal.Signals]] = []
    monkeypatch.setattr(proc.os, "getpgid", lambda _pid: 4312, raising=False)
    monkeypatch.setattr(proc.os, "getpgrp", lambda: 9000, raising=False)
    monkeypatch.setattr(
        proc.os,
        "killpg",
        lambda group, signum: calls.append((group, signum)),
        raising=False,
    )

    assert proc.kill_process_group(process.pid) is True

    assert calls == [(4312, proc._POSIX_KILL_SIGNAL)]
    assert process.killed is False


@pytest.mark.skipif(os.name == "nt", reason="POSIX process groups")
def test_success_cleanup_uses_bounded_term_then_group_kill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signals: list[tuple[int, int]] = []
    waits: list[float] = []

    class _WaitEvent:
        def wait(self, timeout: float) -> bool:
            waits.append(timeout)
            return False

    def current_group() -> int:
        return 9000

    def record_signal(group: int, signum: int) -> None:
        signals.append((group, signum))

    monkeypatch.setattr(os, "getpgrp", current_group)
    monkeypatch.setattr(
        os,
        "killpg",
        record_signal,
    )
    monkeypatch.setattr(threading, "Event", _WaitEvent)

    proc.terminate_posix_process_group(4312)

    assert signals == [
        (4312, signal.SIGTERM),
        (4312, signal.SIGKILL),
    ]
    assert waits == [1.0]


@pytest.mark.skipif(os.name == "nt", reason="POSIX process groups")
def test_success_cleanup_does_not_wait_or_kill_when_group_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signals: list[int] = []
    waited = False

    class _WaitEvent:
        def wait(self, _timeout: float) -> bool:
            nonlocal waited
            waited = True
            return False

    def missing_group(_group: int, signum: int) -> None:
        signals.append(signum)
        raise ProcessLookupError

    def current_group() -> int:
        return 9000

    monkeypatch.setattr(os, "getpgrp", current_group)
    monkeypatch.setattr(os, "killpg", missing_group)
    monkeypatch.setattr(threading, "Event", _WaitEvent)

    proc.terminate_posix_process_group(4312)

    assert signals == [signal.SIGTERM]
    assert waited is False


@pytest.mark.skipif(os.name == "nt", reason="POSIX process groups")
def test_kill_posix_tree_survives_exited_shell_leader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, signal.Signals]] = []
    monkeypatch.setattr(
        proc.os,
        "getpgid",
        lambda _pid: (_ for _ in ()).throw(ProcessLookupError),
    )
    monkeypatch.setattr(proc.os, "getpgrp", lambda: 9000)
    monkeypatch.setattr(
        proc.os,
        "killpg",
        lambda group, signum: calls.append((group, signum)),
    )

    assert proc.kill_process_group(4312) is True
    assert calls == [(4312, signal.SIGKILL)]


def test_run_shell_command_cleans_tree_when_interrupted(monkeypatch) -> None:
    process = _InterruptedProcess()
    killed: list[_InterruptedProcess] = []
    managed = _ManagedTree()
    if os.name == "nt":
        monkeypatch.setattr(
            proc,
            "spawn_managed_windows_shell",
            lambda _argv, _request: (process, managed),
        )
    else:
        monkeypatch.setattr(
            proc,
            "_spawn_shell",
            lambda _argv, _request: process,
        )
    monkeypatch.setattr(proc, "kill_tree", killed.append)
    request = proc.ShellCommand(
        command="long-running-command",
        cwd=None,
        timeout=30,
        environment={},
    )

    with pytest.raises(KeyboardInterrupt):
        proc.run_shell_command(request)

    if os.name == "nt":
        assert killed == []
        assert managed.terminations == [1]
        assert managed.closed is True
    else:
        assert killed == [process]
    assert process.communications == 2


def test_run_shell_command_utf8_stdin_and_merged_streams(
    tmp_path: Path,
) -> None:
    script = tmp_path / "stream probe.py"
    _ = script.write_text(
        "import sys\n"
        "payload = sys.stdin.read()\n"
        "print(f'stdout:{payload}', flush=True)\n"
        "print('stderr:한글✓', file=sys.stderr, flush=True)\n",
        encoding="utf-8",
    )

    result = proc.run_shell_command(
        proc.ShellCommand(
            command=_command([sys.executable, str(script)]),
            cwd=tmp_path,
            timeout=10,
            environment=proc.shell_env(),
            stdin='{"value":"입력"}',
            merge_stderr=True,
        )
    )

    assert result.returncode == 0
    assert result.stdout == (
        'stdout:{"value":"입력"}\n'
        "stderr:한글✓\n"
    )
    assert result.stderr is None


def test_shell_argv_wraps_command_string():
    argv = proc.shell_argv("echo hi")
    if os.name == "nt":
        assert argv[-4:] == [
            "/d",
            "/s",
            "/c",
            f"@{os.environ['SystemRoot']}\\System32\\chcp.com 65001>nul & echo hi",
        ]
        assert argv[0].lower().endswith(r"\system32\cmd.exe")
    else:
        assert argv == ["/bin/bash", "-c", "echo hi"]


def test_windows_shell_argv_uses_native_cmd_without_autorun() -> None:
    argv = proc.windows_shell_argv("echo hi", r"C:\Windows")

    assert argv == [
        r"C:\Windows\System32\cmd.exe",
        "/d",
        "/s",
        "/c",
        "@C:\\Windows\\System32\\chcp.com 65001>nul & echo hi",
    ]


def test_windows_hidden_creation_flags_preserve_process_group() -> None:
    group = proc.windows_creation_flags(False)
    hidden = proc.windows_creation_flags(True)

    assert group & 0x00000200
    assert not group & 0x08000000
    assert hidden & 0x00000200
    assert hidden & 0x08000000


@pytest.mark.skipif(os.name == "nt", reason="POSIX runtime PATH contract")
def test_shell_env_adds_runtime_path_without_login_shell(monkeypatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    environment = proc.shell_env()

    assert str(Path(sys.executable).parent) in environment["PATH"].split(
        os.pathsep
    )


def test_cli_argv_keeps_parts_discrete():
    argv = proc.cli_argv(["claude", "-p", "--model", "sonnet"])
    assert "--model" in argv and "sonnet" in argv
    if os.name == "nt":
        assert argv[:2] == ["cmd", "/c"]
        assert os.path.basename(argv[2]).lower() in ("claude", "claude.cmd")
    else:
        assert argv == ["claude", "-p", "--model", "sonnet"]


@pytest.mark.skipif(os.name != "nt", reason="Windows npm shim lookup")
def test_cli_argv_falls_back_to_user_npm_shim(monkeypatch, tmp_path):
    # Simulating "nt" on POSIX is not enough here: pathlib.Path picks its
    # flavour from os.name at construction time, so cli_argv's Path(APPDATA)
    # would raise NotImplementedError, and pytest's own failure reporting
    # (which also builds a Path) would then abort the whole session with an
    # INTERNALERROR instead of reporting one failed test.
    appdata = tmp_path / "AppData" / "Roaming"
    npm = appdata / "npm"
    npm.mkdir(parents=True)
    shim = npm / "claude.cmd"
    shim.write_text("@echo off\r\n", encoding="utf-8")
    monkeypatch.setattr(proc.os, "name", "nt")
    monkeypatch.setenv("APPDATA", str(appdata))

    argv = proc.cli_argv(["claude", "--version"])

    assert argv == ["cmd", "/c", str(shim), "--version"]


def test_cli_argv_rejects_windows_shell_metachars(monkeypatch):
    # On Windows, cmd /c re-parses metacharacters inside each arg, so a smuggled
    # `& calc` would chain a second command — cli_argv must reject it.
    monkeypatch.setattr(proc.os, "name", "nt")
    # Keep the simulated branch off pathlib: with APPDATA set, cli_argv builds a
    # Path, which cannot be a WindowsPath on POSIX.
    monkeypatch.delenv("APPDATA", raising=False)
    for bad in ("foo & calc", "a|b", "x>out", "y<in", "z^a"):
        with pytest.raises(ValueError):
            proc.cli_argv(["claude", "mcp", "add", "srv", bad])
    # The program name itself is trusted and not scanned; clean args pass.
    assert proc.cli_argv(["claude", "mcp", "list"])[:2] == ["cmd", "/c"]


def test_cli_argv_allows_metachars_on_posix(monkeypatch):
    # POSIX uses a discrete argv with no shell, so metachars are literal data.
    monkeypatch.setattr(proc.os, "name", "posix")
    assert proc.cli_argv(["claude", "x & y"]) == ["claude", "x & y"]


@pytest.mark.skipif(os.name != "nt", reason="Windows native shim fallback")
def test_policy_failure_tries_deterministic_safe_native_shims(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Given: PATHEXT prefers PowerShell and every safe native candidate exists.
    bin_dir = tmp_path / "native-bin"
    bin_dir.mkdir()
    for extension in (".ps1", ".com", ".exe", ".bat", ".cmd"):
        (bin_dir / f"bunx{extension}").touch()
    request = _native_request("bunx package@latest submit", tmp_path)
    request.environment["PATH"] = str(bin_dir)
    request.environment["PATHEXT"] = ".PS1;.CMD;.BAT;.EXE;.COM"
    original = (
        1,
        "original stdout",
        "bunx.ps1 cannot be loaded because running scripts is disabled. "
        "PSSecurityException",
    )
    script = _ScriptedWindowsShell(
        [original, *(4 * [(1, "", "native candidate failed")])]
    )
    monkeypatch.setattr(proc, "spawn_managed_windows_shell", script)

    # When: the extensionless command is blocked by PowerShell policy.
    result = proc.run_shell_command(request)

    # Then: only safe candidates run in fixed order and original failure wins.
    assert [attempt[0] for attempt in script.attempts] == [
        request.command,
        f"{bin_dir / 'bunx.com'} package@latest submit",
        f"{bin_dir / 'bunx.exe'} package@latest submit",
        f"{bin_dir / 'bunx.bat'} package@latest submit",
        f"{bin_dir / 'bunx.cmd'} package@latest submit",
    ]
    assert all(
        ".ps1" not in command.casefold()
        for command, _request in script.attempts[1:]
    )
    assert result.returncode == original[0]
    assert result.stdout == original[1]
    assert result.stderr == original[2]


@pytest.mark.skipif(os.name != "nt", reason="Windows native shim fallback")
def test_native_shim_fallback_preserves_exact_command_suffix(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Given: an exe failure followed by a cmd success for one exact suffix.
    bin_dir = tmp_path / "native-bin"
    bin_dir.mkdir()
    executable = bin_dir / "bunx.exe"
    command_shim = bin_dir / "bunx.cmd"
    executable.touch()
    command_shim.touch()
    request = _native_request("bunx tokscale@latest submit", tmp_path)
    request.environment["PATH"] = str(bin_dir)
    request.environment["PATHEXT"] = ".EXE;.CMD"
    script = _ScriptedWindowsShell([
        (
            1,
            "",
            "bunx.ps1 cannot be loaded because running scripts is disabled. "
            "PSSecurityException",
        ),
        (1, "", "exe failed"),
        (0, "native-shim-fallback-ok", ""),
    ])
    monkeypatch.setattr(proc, "spawn_managed_windows_shell", script)

    # When: the safe native fallback reaches the working cmd shim.
    result = proc.run_shell_command(request)

    # Then: only the executable token changes; package and action stay exact.
    assert [attempt[0] for attempt in script.attempts] == [
        request.command,
        f"{executable} tokscale@latest submit",
        f"{command_shim} tokscale@latest submit",
    ]
    assert result.returncode == 0
    assert result.stdout == "native-shim-fallback-ok"


@pytest.mark.skipif(os.name != "nt", reason="Windows native shim fallback")
def test_policy_failure_for_unrelated_script_does_not_retry_native_shim(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Given: a policy diagnostic names other.ps1, not the bunx command.
    request = _native_request("bunx --version", tmp_path)
    script = _ScriptedWindowsShell([
        (
            1,
            "",
            "other.ps1 cannot be loaded because running scripts is disabled. "
            "PSSecurityException",
        ),
    ])
    monkeypatch.setattr(proc, "spawn_managed_windows_shell", script)

    # When: the unrelated failure is returned.
    result = proc.run_shell_command(request)

    # Then: no alternative executable receives the command's authority.
    assert [attempt[0] for attempt in script.attempts] == [request.command]
    assert result.returncode == 1


@pytest.mark.skipif(os.name != "nt", reason="Windows native shim fallback")
def test_shim_fallback_shares_one_monotonic_timeout_budget(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Given: each completed attempt consumes two seconds of a ten-second budget.
    bin_dir = tmp_path / "native-bin"
    bin_dir.mkdir()
    executable = bin_dir / "bunx.exe"
    command_shim = bin_dir / "bunx.cmd"
    executable.touch()
    command_shim.touch()
    request = _native_request("bunx package submit", tmp_path, timeout=10)
    request.environment["PATH"] = str(bin_dir)
    request.environment["PATHEXT"] = ".EXE;.CMD"
    now = [100.0]
    script = _ScriptedWindowsShell(
        [
            (
                1,
                "",
                "bunx.ps1 cannot be loaded because running scripts is disabled. "
                "PSSecurityException",
            ),
            (1, "", "exe failed"),
            (0, "ok", ""),
        ],
        advance=lambda: now.__setitem__(0, now[0] + 2.0),
    )
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    monkeypatch.setattr(proc, "spawn_managed_windows_shell", script)

    # When: fallback consumes multiple attempts.
    result = proc.run_shell_command(request)

    # Then: each attempt receives only the remaining original timeout.
    assert result.returncode == 0
    assert script.timeouts == [10, 8, 6]


# -- claude_child_env: disable the ECC interactive SessionStart hook -------
#
# birkin spawns `claude` as an engine and injects its OWN persona/memory/skills.
# The ECC plugin's SessionStart hook injects an unrelated "Previous session
# summary" which the model then surfaces on the first turn — leaking a session
# dump into gateway/Telegram replies. claude_child_env disables it per-subprocess.

def _disabled_ids(env: dict[str, str]) -> list[str]:
    return [h.strip() for h in env.get("ECC_DISABLED_HOOKS", "").split(",")
            if h.strip()]


def test_claude_child_env_disables_session_start_hook():
    assert "session:start" in _disabled_ids(proc.claude_child_env())


def test_claude_child_env_preserves_existing_disabled_hooks(monkeypatch):
    monkeypatch.setenv("ECC_DISABLED_HOOKS", "foo:bar")
    ids = _disabled_ids(proc.claude_child_env())
    assert "foo:bar" in ids and "session:start" in ids


def test_claude_child_env_is_idempotent(monkeypatch):
    """Already-disabled session:start must not be duplicated."""
    monkeypatch.setenv("ECC_DISABLED_HOOKS", "session:start")
    assert _disabled_ids(proc.claude_child_env()).count("session:start") == 1


def test_claude_child_env_inherits_parent_env(monkeypatch):
    monkeypatch.setenv("BIRKIN_TEST_SENTINEL", "xyz")
    assert proc.claude_child_env().get("BIRKIN_TEST_SENTINEL") == "xyz"
