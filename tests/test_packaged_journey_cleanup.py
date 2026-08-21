from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/native/packaged_journey.sh"


@pytest.mark.parametrize(
    ("failure_mode", "expected_status"),
    [("after-fixture", 97), ("signal-term", 143)],
)
def test_forced_failure_and_signal_cleanup_every_resource(
    tmp_path: Path,
    failure_mode: str,
    expected_status: int,
) -> None:
    evidence = tmp_path / "evidence"
    environment = {
        **os.environ,
        "BIRKIN_NATIVE_JOURNEY_FORCE_FAILURE": failure_mode,
    }

    result = subprocess.run(
        ["bash", str(SCRIPT), str(evidence), str(tmp_path / "missing-dist")],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == expected_status, result.stdout + result.stderr
    report = dict(
        line.split("=", 1)
        for line in (evidence / "packaged-journey-cleanup.txt")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert report["failure_mode"] == failure_mode
    assert report["root_exists"] == "no"
    assert report["app_running"] == "no"
    assert report["browser_running"] == "no"
    assert report["bridge_processes"] == "0"
    assert report["socket_exists"] == "no"
    assert not Path(report["root"]).exists()
    browser_pid = int(report["browser_pid"])
    with pytest.raises(ProcessLookupError):
        os.kill(browser_pid, 0)
