from __future__ import annotations

import subprocess
from pathlib import Path

from birkin.sandbox import NetworkPolicy, PolicyRequest, SandboxJob, SandboxPolicy
from birkin.sandbox_docker import DockerRunner


class RecordingDriver:
    def __init__(self) -> None:
        self.argv: list[str] = []

    def run(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
        self.argv = argv
        return subprocess.CompletedProcess(argv, 0, "ok", "")


def test_docker_command_has_reproducible_setup_and_hard_mount_scopes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    driver = RecordingDriver()
    runner = DockerRunner(repo, driver=driver)
    policy = SandboxPolicy(
        network=NetworkPolicy.OFF,
        env_allowlist=("TOKEN",),
        write_paths=("src",),
    )
    job = SandboxJob(
        command=("python", "-m", "pytest"),
        setup=("python -m pip install -e .",),
        image="python:3.12-slim@sha256:" + "b" * 64,
        request=PolicyRequest(write_paths=("src/generated.py",)),
    )

    result = runner.run(job, policy, source_env={"TOKEN": "yes", "HOME": "no"})

    assert result.returncode == 0
    command = driver.argv
    assert command[:2] == ["docker", "run"]
    assert "--network=none" in command
    assert "TOKEN=yes" in command
    assert not any("HOME=" in part for part in command)
    mounts = [command[i + 1] for i, value in enumerate(command) if value == "--mount"]
    assert any("dst=/workspace,readonly" in mount for mount in mounts)
    assert any("dst=/workspace/src" in mount and "readonly" not in mount for mount in mounts)
    assert "python -m pip install -e ." in command[-5]
    assert command[-3:] == ["python", "-m", "pytest"]
