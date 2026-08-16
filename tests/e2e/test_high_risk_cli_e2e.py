"""Subprocess contracts for high-risk CLI trust boundaries."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def _run(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["BIRKIN_HOME"] = str(home)
    env["NO_COLOR"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "birkin", *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.mark.parametrize(
    "command",
    [
        "plugins",
        "web",
        "gateway",
        "voice",
        "daemon",
        "auth",
        "review",
        "permission",
    ],
)
def test_high_risk_command_help_is_subprocess_safe(
    tmp_path: Path,
    command: str,
) -> None:
    result = _run(tmp_path, command, "--help")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "usage:" in result.stdout


def test_high_risk_status_paths_do_not_cross_external_boundaries(
    tmp_path: Path,
) -> None:
    for args in (
        ("voice", "status"),
        ("auth", "codex", "status"),
        ("review",),
        ("permission",),
    ):
        result = _run(tmp_path, *args)
        assert result.returncode in {0, 1}, result.stdout + result.stderr
        assert "https://" not in result.stdout


def test_plugins_rejects_missing_source_without_execution(tmp_path: Path) -> None:
    marker = tmp_path / "executed"
    result = _run(
        tmp_path,
        "plugins",
        "install",
        str(tmp_path / "missing"),
        "--version",
        "1.0.0",
        "--yes",
    )

    assert result.returncode != 0
    assert not marker.exists()
