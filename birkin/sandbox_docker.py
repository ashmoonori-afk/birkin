"""Docker sandbox command construction and execution."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Mapping, Protocol

from .sandbox import NetworkPolicy, SandboxJob, SandboxPolicy, SandboxResult


class DockerDriver(Protocol):
    def run(self, argv: list[str]) -> subprocess.CompletedProcess[str]: ...


class DockerCLI:
    def run(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                argv, text=True, encoding="utf-8", errors="replace",
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("Docker CLI is not installed") from exc


class DockerRunner:
    def __init__(self, repo: Path, *, driver: DockerDriver | None = None) -> None:
        self.repo = repo.resolve()
        self.driver = driver or DockerCLI()

    @staticmethod
    def _mount(source: Path, destination: str, *, readonly: bool = False) -> str:
        value = f"type=bind,src={source},dst={destination}"
        return value + (",readonly" if readonly else "")

    def command(self, job: SandboxJob, policy: SandboxPolicy,
                source_env: Mapping[str, str]) -> list[str]:
        policy.require(job.request)
        if not job.image:
            raise ValueError("Docker jobs require an image")
        argv = ["docker", "run", "--rm", "--workdir=/workspace"]
        argv.append("--network=none" if policy.network is NetworkPolicy.OFF
                    else "--network=bridge")
        writable_root = "." in policy.write_paths
        argv += ["--mount", self._mount(self.repo, "/workspace", readonly=not writable_root)]
        for raw in policy.write_paths:
            if raw == ".":
                continue  # already mounted read-write above; a second dst=/workspace is rejected
            argv += ["--mount", self._mount(self.repo / raw, f"/workspace/{raw}")]
        for name, value in policy.environment(source_env).items():
            argv += ["--env", f"{name}={value}"]
        if policy.network is NetworkPolicy.ALLOWLIST:
            argv += ["--env", "BIRKIN_NETWORK_ALLOWLIST=" + ",".join(policy.network_allowlist)]
        setup = "\n".join(job.setup)
        script = "set -eu\n" + (setup + "\n" if setup else "") + 'exec "$@"'
        return argv + [job.image, "sh", "-lc", script, "sh", *job.command]

    def run(self, job: SandboxJob, policy: SandboxPolicy, *,
            source_env: Mapping[str, str] | None = None) -> SandboxResult:
        proc = self.driver.run(self.command(
            job, policy, source_env if source_env is not None else os.environ
        ))
        return SandboxResult(proc.returncode, proc.stdout or "", proc.stderr or "")
