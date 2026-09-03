from __future__ import annotations

from pathlib import Path

from birkin.sandbox import PolicyRequest, SandboxJob, SandboxPolicy
from birkin.sandbox_docker import DockerRunner


def test_default_write_scope_mounts_workspace_once_writable(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    runner = DockerRunner(repo)
    job = SandboxJob(
        command=("python", "-m", "pytest"),
        image="python:3.12-slim@sha256:" + "c" * 64,
        request=PolicyRequest(write_paths=("generated.py",)),
    )

    command = runner.command(job, SandboxPolicy(), source_env={})

    mounts = [command[i + 1] for i, value in enumerate(command) if value == "--mount"]
    destinations = [mount.split("dst=")[1].split(",")[0] for mount in mounts]
    assert destinations == ["/workspace"]
    assert "readonly" not in mounts[0]
