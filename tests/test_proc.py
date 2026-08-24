import os
import shlex
import signal
import subprocess
import sys
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
def test_kill_posix_tree_survives_exited_shell_leader(monkeypatch) -> None:
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
    assert calls == [(4312, proc._POSIX_KILL_SIGNAL)]


def test_run_shell_command_cleans_tree_when_interrupted(monkeypatch) -> None:
    process = _InterruptedProcess()
    killed: list[_InterruptedProcess] = []
    managed = _ManagedTree()
    if os.name == "nt":
        monkeypatch.setattr(
            proc,
            "_spawn_managed_windows_shell",
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
