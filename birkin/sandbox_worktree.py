"""Disposable git-worktree sandbox runner."""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Callable, Mapping

from .proc import ShellCommand, run_shell_command
from .sandbox import PolicyRequest, SandboxJob, SandboxPolicy, SandboxResult


def _timeout_text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value or ""


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
        # --ignored=matching: .gitignore'd writes (build/, .venv/, node_modules/) are
        # still out-of-scope writes and must reach the policy gate as "!! <path>".
        output = self._git(
            "status", "--porcelain=v1", "-z", "--ignored=matching", cwd=worktree
        ).stdout
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
        runtime_temp = self.sandbox_root / f"temp-{uuid.uuid4().hex}"
        runtime_temp.mkdir()
        stdout: list[str] = []
        stderr: list[str] = []
        try:
            self._git("worktree", "add", "--detach", str(worktree), "HEAD")
            if self.on_created:
                self.on_created(worktree)
            if seed is not None:
                seed(worktree)
            source = source_env if source_env is not None else os.environ
            env = policy.environment(source)
            for name in ("PATH", "PATHEXT", "SystemRoot", "ComSpec"):
                value = source.get(name)
                if value:
                    env.setdefault(name, value)
            env.update(
                TMPDIR=str(runtime_temp),
                TEMP=str(runtime_temp),
                TMP=str(runtime_temp),
            )
            if os.name == "nt":
                env["PYTHONUTF8"] = "1"
            for setup in job.setup:
                try:
                    proc = run_shell_command(
                        ShellCommand(
                            command=setup,
                            cwd=worktree,
                            timeout=1800,
                            environment=env,
                            hide_window=True,
                        )
                    )
                except subprocess.TimeoutExpired as exc:
                    stdout.append(_timeout_text(exc.stdout))
                    stderr.append(_timeout_text(exc.stderr))
                    return SandboxResult(
                        124,
                        "".join(stdout),
                        "".join(stderr),
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
            shutil.rmtree(runtime_temp, ignore_errors=True)
            self._git("worktree", "prune", check=False)
