"""Every free-form shell string uses the managed process-tree runner."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import final

import pytest

from birkin import github_action, hooks, sandbox_worktree
from birkin.proc import ShellCommand
from birkin.sandbox import PolicyRequest, SandboxJob, SandboxPolicy
from birkin.sandbox_worktree import WorktreeRunner


@final
class _Completed:
    returncode: int
    stdout: str
    stderr: str

    def __init__(
        self,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _command(parts: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(parts)
    return shlex.join(parts)


def _git(repo: Path, *args: str) -> None:
    _ = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _ = (repo / "tracked.txt").write_text("base", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    return repo


def test_github_action_test_command_uses_managed_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[ShellCommand] = []

    def run(request: ShellCommand) -> _Completed:
        calls.append(request)
        return _Completed(7, "test-output")

    monkeypatch.setattr(
        github_action,
        "run_shell_command",
        run,
        raising=False,
    )

    returncode, output = github_action.run_test_command(
        "python -m pytest -q"
    )

    assert returncode == 7
    assert output == "test-output"
    assert len(calls) == 1
    assert calls[0].command == "python -m pytest -q"
    assert calls[0].hide_window is True
    assert calls[0].merge_stderr is True


def test_github_action_timeout_returns_retryable_partial_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def run(_request: ShellCommand) -> _Completed:
        raise subprocess.TimeoutExpired(
            ["shell"],
            3600,
            output="partial-stdout\n",
            stderr="partial-stderr\n",
        )

    monkeypatch.setattr(github_action, "run_shell_command", run)

    returncode, output = github_action.run_test_command("long test command")

    assert returncode == 124
    assert output == "partial-stdout\npartial-stderr\n"


def test_github_action_test_command_executes_real_unicode_shell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "한글 action workspace"
    workspace.mkdir()
    script = workspace / "action probe.py"
    _ = script.write_text(
        "import sys\n"
        + "print('action-stdout:한글', flush=True)\n"
        + "print('action-stderr:✓', file=sys.stderr, flush=True)\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(workspace)

    returncode, output = github_action.run_test_command(
        _command([sys.executable, str(script)])
    )

    assert returncode == 0
    assert output == "action-stdout:한글\naction-stderr:✓\n"


def test_hook_command_uses_managed_runner_with_json_stdin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[ShellCommand] = []

    def run(request: ShellCommand) -> _Completed:
        calls.append(request)
        return _Completed(stdout='{"context":"approved"}')

    monkeypatch.setattr(hooks, "run_shell_command", run, raising=False)
    spec = hooks.HookSpec(
        event="pre_llm_call",
        command="python hook.py",
        timeout=9,
    )

    result = hooks.run_hook(spec, {"event": "pre_llm_call"})

    assert result == {"context": "approved"}
    assert len(calls) == 1
    assert calls[0].command == "python hook.py"
    assert calls[0].timeout == 9
    assert calls[0].stdin == '{"event": "pre_llm_call"}'
    assert calls[0].hide_window is True


def test_worktree_setup_uses_managed_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    calls: list[ShellCommand] = []

    def run(request: ShellCommand) -> _Completed:
        calls.append(request)
        assert request.environment["PATH"] == "trusted-path"
        assert "BIRKIN_SECRET" not in request.environment
        temp = Path(request.environment["TEMP"])
        assert request.environment["TMP"] == str(temp)
        assert temp.is_dir()
        _ = (temp / "probe.txt").write_text("ok", encoding="utf-8")
        return _Completed(stdout="setup-output")

    monkeypatch.setattr(
        sandbox_worktree,
        "run_shell_command",
        run,
        raising=False,
    )
    runner = WorktreeRunner(repo, sandbox_root=tmp_path / "sandboxes")
    job = SandboxJob(
        command=(sys.executable, "-c", "raise SystemExit(0)"),
        setup=("python setup.py && echo ready",),
        request=PolicyRequest(),
    )

    result = runner.run(
        job,
        SandboxPolicy(),
        source_env={
            "PATH": "trusted-path",
            "BIRKIN_SECRET": "must-not-cross",
        },
    )

    assert result.returncode == 0
    assert result.stdout.startswith("setup-output")
    assert len(calls) == 1
    assert calls[0].command == "python setup.py && echo ready"
    assert calls[0].hide_window is True
    assert not Path(calls[0].environment["TEMP"]).exists()


def test_worktree_setup_timeout_returns_result_and_cleans(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _ = (repo / "tracked.txt").write_text("base", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    created: list[Path] = []

    def run(_request: ShellCommand) -> _Completed:
        raise subprocess.TimeoutExpired(
            ["shell"],
            1800,
            output="setup-partial",
            stderr="setup-timeout",
        )

    monkeypatch.setattr(sandbox_worktree, "run_shell_command", run)
    runner = WorktreeRunner(
        repo,
        sandbox_root=tmp_path / "sandboxes",
        on_created=created.append,
    )

    result = runner.run(
        SandboxJob(command=(sys.executable,), setup=("long setup",)),
        SandboxPolicy(),
        source_env={"PATH": "trusted-path"},
    )

    assert result.returncode == 124
    assert result.stdout == "setup-partial"
    assert result.stderr == "setup-timeout"
    assert created and not created[0].exists()
