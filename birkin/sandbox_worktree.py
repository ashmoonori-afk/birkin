"""Disposable git-worktree sandbox runner."""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Callable, Mapping

from .sandbox import PolicyRequest, SandboxJob, SandboxPolicy, SandboxResult


class WorktreeRunner:
    def __init__(self, repo: Path, *, sandbox_root: Path | None = None,
                 on_created: Callable[[Path], None] | None = None) -> None:
        self.repo = repo.resolve()
        self.sandbox_root = (sandbox_root or self.repo.parent / ".birkin-sandboxes").resolve()
        self.on_created = on_created

    def _git(self, *args: str, cwd: Path | None = None,
             check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args], cwd=cwd or self.repo, check=check,
            text=True, encoding="utf-8", errors="replace",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    def _changed_paths(self, worktree: Path) -> tuple[str, ...]:
        output = self._git("status", "--porcelain=v1", "-z", cwd=worktree).stdout
        entries = output.split("\0")
        paths: list[str] = []
        skip_rename_source = False
        for entry in entries:
            if not entry:
                continue
            if skip_rename_source:
                skip_rename_source = False
                continue
            status, path = entry[:2], entry[3:]
            paths.append(path.replace("\\", "/"))
            if "R" in status or "C" in status:
                skip_rename_source = True
        return tuple(paths)

    def run(self, job: SandboxJob, policy: SandboxPolicy, *,
            source_env: Mapping[str, str] | None = None,
            seed: Callable[[Path], None] | None = None) -> SandboxResult:
        policy.require(job.request)
        self.sandbox_root.mkdir(parents=True, exist_ok=True)
        worktree = self.sandbox_root / f"job-{uuid.uuid4().hex}"
        self._git("worktree", "add", "--detach", str(worktree), "HEAD")
        stdout: list[str] = []
        stderr: list[str] = []
        try:
            if self.on_created:
                self.on_created(worktree)
            if seed is not None:
                seed(worktree)
            env = policy.environment(source_env if source_env is not None else os.environ)
            for setup in job.setup:
                proc = subprocess.run(
                    setup, cwd=worktree, env=env, shell=True, text=True,
                    encoding="utf-8", errors="replace", capture_output=True,
                )
                stdout.append(proc.stdout)
                stderr.append(proc.stderr)
                if proc.returncode:
                    return SandboxResult(proc.returncode, "".join(stdout), "".join(stderr))
            proc = subprocess.run(
                list(job.command), cwd=worktree, env=env, text=True,
                encoding="utf-8", errors="replace", capture_output=True,
            )
            stdout.append(proc.stdout)
            stderr.append(proc.stderr)
            changed = self._changed_paths(worktree)
            policy.require(PolicyRequest(write_paths=changed))
            return SandboxResult(proc.returncode, "".join(stdout), "".join(stderr))
        finally:
            self._git("worktree", "remove", "--force", str(worktree), check=False)
            shutil.rmtree(worktree, ignore_errors=True)
            self._git("worktree", "prune", check=False)
