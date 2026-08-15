from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _run(
    tmp_path: Path,
    *args: str,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["BIRKIN_HOME"] = str(tmp_path / "home")
    return subprocess.run(
        [sys.executable, "-m", "birkin", "computer-use", *args],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_computer_use_help_is_explicit(tmp_path: Path) -> None:
    result = _run(tmp_path, "--help")

    assert result.returncode == 0
    assert "doctor" in result.stdout
    assert "setup" in result.stdout


def test_computer_use_doctor_json_is_machine_readable(tmp_path: Path) -> None:
    result = _run(tmp_path, "doctor", "--json")

    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["schema_version"] == "1"
    assert report["permission_prompted"] is False


def test_computer_use_invalid_command_exits_two(tmp_path: Path) -> None:
    result = _run(tmp_path, "capture")

    assert result.returncode == 2
    assert "invalid choice" in result.stderr


def test_computer_use_setup_only_prints_explicit_actions(
    tmp_path: Path,
) -> None:
    result = _run(tmp_path, "setup", "--json")

    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["performed_actions"] == []
    assert report["install_command"]
    assert report["permission_actions"] or report["system_requirements"]
