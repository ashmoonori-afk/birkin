from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from birkin.sandbox import SandboxJob, SandboxPolicy, SandboxViolation
from birkin.sandbox_worktree import WorktreeRunner


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _repo_with_gitignore(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / ".gitignore").write_text("build/\n", encoding="utf-8")
    (repo / "tracked.txt").write_text("base", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    return repo


def test_worktree_detects_write_into_gitignored_path(tmp_path: Path) -> None:
    repo = _repo_with_gitignore(tmp_path)
    roots: list[Path] = []
    runner = WorktreeRunner(repo, sandbox_root=tmp_path / "sandboxes",
                            on_created=roots.append)
    job = SandboxJob(
        command=(
            sys.executable, "-c",
            "import pathlib; pathlib.Path('build').mkdir(); "
            "pathlib.Path('build/postinstall.py').write_text('evil')",
        ),
    )

    with pytest.raises(SandboxViolation, match="build"):
        runner.run(job, SandboxPolicy(write_paths=("src",)))

    assert roots and not roots[0].exists()
