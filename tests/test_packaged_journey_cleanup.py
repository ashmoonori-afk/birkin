from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/native/packaged_journey.sh"
SUPPORTED_PLATFORMS: Final = frozenset({"darwin", "linux"})
pytestmark = pytest.mark.skipif(
    sys.platform not in SUPPORTED_PLATFORMS,
    reason="packaged journey cleanup requires POSIX process groups",
)


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
    assert report["process_event_backend"] == (
        "pidfd" if sys.platform.startswith("linux") else "kqueue"
    )
    assert report["bridge_overrides"] == "absent"
    assert report["home_exists"] == "no"
    assert report["search_path"] == "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    assert report["socket_exists"] == "no"
    assert not Path(report["root"]).exists()
    browser_pid = int(report["browser_pid"])
    with pytest.raises(ProcessLookupError):
        os.kill(browser_pid, 0)


def test_cleanup_reaps_the_owned_app_bridge_process_group_before_reporting(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    dist = tmp_path / "dist"
    app = dist / "Birkin.app/Contents/MacOS/BirkinNativeApp"
    helper = dist / "Birkin.app/Contents/Helpers/arm64/birkin-native-bridge"
    app.parent.mkdir(parents=True)
    helper.parent.mkdir(parents=True)
    _ = helper.write_text(
        """#!/bin/bash
if [[ "$*" == *"provider-probe"* ]]; then
  exit 0
fi
trap '' TERM
/usr/bin/python3 -c 'import signal; signal.signal(signal.SIGTERM, signal.SIG_IGN); signal.pause()' &
echo "$BASHPID $!" > "$BIRKIN_NATIVE_JOURNEY_EVIDENCE/bridge-pids"
printf 'ready\\n' > "$BIRKIN_NATIVE_JOURNEY_EVIDENCE/bridge-ready"
wait
""",
        encoding="utf-8",
    )
    _ = app.write_text(
        f"""#!/bin/bash
mkfifo "$BIRKIN_NATIVE_JOURNEY_EVIDENCE/bridge-ready"
/usr/bin/python3 -c 'import os, sys; os.setsid(); os.execv(sys.argv[1], sys.argv[1:])' \
  "{helper}" native-bridge serve --transport uds &
IFS= read -r _ < "$BIRKIN_NATIVE_JOURNEY_EVIDENCE/bridge-ready"
exit 73
""",
        encoding="utf-8",
    )
    _ = helper.chmod(0o755)
    _ = app.chmod(0o755)

    result = subprocess.run(
        ["bash", str(SCRIPT), str(evidence), str(dist)],
        cwd=ROOT,
        env=os.environ,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode != 0
    report = dict(
        line.split("=", 1)
        for line in (evidence / "packaged-journey-cleanup.txt")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert report["app_running"] == "no"
    assert report["browser_running"] == "no"
    assert report["bridge_processes"] == "0"
    assert report["process_event_backend"] == (
        "pidfd" if sys.platform.startswith("linux") else "kqueue"
    )
    live_pids: list[int] = []
    for pid in map(int, (evidence / "bridge-pids").read_text().split()):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        live_pids.append(pid)
    for pid in live_pids:
        os.kill(pid, 9)
    assert live_pids == []


def test_journey_uses_only_the_packaged_bridge_helper() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    assert ".venv" not in script
    for variable in (
        "BIRKIN_NATIVE_BRIDGE_COMMAND",
        "BIRKIN_NATIVE_BRIDGE_ARGUMENTS",
        "BIRKIN_NATIVE_BRIDGE_OPTIONS",
    ):
        assert f"export {variable}" not in script
        assert f"unset {variable}" in script
    assert "native-bridge provider-probe" in script
    assert "Darwin) process_event_backend=kqueue" in script
    assert "Linux) process_event_backend=pidfd" in script
    assert 'export HOME="$root/empty-home"' in script
    assert "Library/Caches/ms-playwright" not in script
