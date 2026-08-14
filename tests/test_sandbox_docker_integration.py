from __future__ import annotations

import os
import subprocess

import pytest


pytestmark = [
    pytest.mark.docker_integration,
    pytest.mark.skipif(
        os.environ.get("BIRKIN_DOCKER_INTEGRATION") != "1",
        reason="set BIRKIN_DOCKER_INTEGRATION=1 to use a local Docker daemon",
    ),
]


def test_docker_daemon_is_available_for_opt_in_smoke() -> None:
    proc = subprocess.run(
        ["docker", "info"], capture_output=True, text=True, check=False, timeout=30
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
