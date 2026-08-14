from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from birkin.sandbox import PolicyRequest, SandboxJob, SandboxPolicy, SandboxViolation
from birkin.sandbox_worktree import WorktreeRunner


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "tracked.txt").write_text("base", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    return repo


def test_worktree_lifecycle_setup_env_and_cleanup(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    roots: list[Path] = []
    runner = WorktreeRunner(repo, sandbox_root=tmp_path / "sandboxes",
                            on_created=roots.append)
    policy = SandboxPolicy(env_allowlist=("VISIBLE",), write_paths=("out",))
    code = (
        "import os,pathlib; "
        "assert os.environ.get('VISIBLE') == 'yes'; "
        "assert 'HIDDEN' not in os.environ; "
        "assert pathlib.Path('setup.txt').read_text() == 'ready'; "
        "pathlib.Path('out').mkdir(); pathlib.Path('out/result.txt').write_text('ok')"
    )
    job = SandboxJob(
        command=(sys.executable, "-c", code),
        setup=(f'"{sys.executable}" -c "open(\'setup.txt\',\'w\').write(\'ready\')"',),
        request=PolicyRequest(write_paths=("out/result.txt", "setup.txt")),
    )
    policy = SandboxPolicy(env_allowlist=("VISIBLE",), write_paths=("out", "setup.txt"))

    result = runner.run(job, policy, source_env={"VISIBLE": "yes", "HIDDEN": "no"})

    assert result.returncode == 0
    assert roots and not roots[0].exists()
    assert not (repo / "out").exists()


def test_worktree_detects_actual_out_of_scope_write_and_cleans(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    roots: list[Path] = []
    runner = WorktreeRunner(repo, sandbox_root=tmp_path / "sandboxes",
                            on_created=roots.append)
    job = SandboxJob(
        command=(sys.executable, "-c", "open('forbidden.txt','w').write('no')"),
        request=PolicyRequest(),
    )

    with pytest.raises(SandboxViolation, match="forbidden.txt"):
        runner.run(job, SandboxPolicy(write_paths=("allowed",)))

    assert roots and not roots[0].exists()


def test_cleanup_happens_when_command_fails(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    roots: list[Path] = []
    runner = WorktreeRunner(repo, sandbox_root=tmp_path / "sandboxes",
                            on_created=roots.append)
    job = SandboxJob(command=(sys.executable, "-c", "raise SystemExit(7)"))

    result = runner.run(job, SandboxPolicy(), source_env={})

    assert result.returncode == 7
    assert roots and not roots[0].exists()
