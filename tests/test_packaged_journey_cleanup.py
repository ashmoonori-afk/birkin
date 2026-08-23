from __future__ import annotations

import os
import platform
import select
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


def _await_process_exit(pid: int) -> bool:
    try:
        if sys.platform.startswith("linux"):
            watcher = os.pidfd_open(pid)
            try:
                return bool(select.select([watcher], [], [], 5.0)[0])
            finally:
                os.close(watcher)
        watcher = select.kqueue()
        try:
            _ = watcher.control(
                [select.kevent(
                    pid,
                    filter=select.KQ_FILTER_PROC,
                    flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE,
                    fflags=select.KQ_NOTE_EXIT,
                )],
                0,
                0,
            )
            return bool(watcher.control(None, 1, 5.0))
        finally:
            watcher.close()
    except (OSError, ProcessLookupError):
        return True


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


def test_evidence_permissions_override_permissive_umask_and_directory(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir(mode=0o777)
    evidence.chmod(0o777)
    environment = {
        **os.environ,
        "BIRKIN_NATIVE_JOURNEY_FORCE_FAILURE": "after-fixture",
    }

    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            'umask 022; exec "$@"',
            "bash",
            str(SCRIPT),
            str(evidence),
            str(tmp_path / "missing-dist"),
        ],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 97, result.stdout + result.stderr
    assert evidence.stat().st_mode & 0o777 == 0o700
    report = evidence / "packaged-journey-cleanup.txt"
    assert report.stat().st_mode & 0o777 == 0o600


def test_evidence_output_files_replace_symlinks_without_touching_targets(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    output_names = (
        "provider-probe.log",
        "packaged-journey-events.log",
        "packaged-journey-cleanup.txt",
    )
    victims: dict[str, Path] = {}
    for name in output_names:
        victim = tmp_path / f"{name}.victim"
        _ = victim.write_text(f"sentinel:{name}", encoding="utf-8")
        (evidence / name).symlink_to(victim)
        victims[name] = victim

    dist = tmp_path / "dist"
    architecture = {
        "arm64": "arm64",
        "aarch64": "arm64",
        "x86_64": "x86_64",
    }[platform.machine()]
    helper = (
        dist
        / "Birkin.app"
        / "Contents"
        / "Helpers"
        / architecture
        / "birkin-native-bridge"
    )
    app = dist / "Birkin.app/Contents/MacOS/BirkinNativeApp"
    helper.parent.mkdir(parents=True)
    app.parent.mkdir(parents=True)
    _ = helper.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    _ = app.write_text(
        """#!/bin/bash
echo 'BIRKIN_APP_EVENT fixture-app-started'
exit 73
""",
        encoding="utf-8",
    )
    helper.chmod(0o755)
    app.chmod(0o755)

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
    for name, victim in victims.items():
        assert victim.read_text(encoding="utf-8") == f"sentinel:{name}"
        output = evidence / name
        assert output.is_file()
        assert not output.is_symlink()


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
bridge_pid=$!
owner_digest=$(/usr/bin/python3 -c \
  'import hashlib, os; print(hashlib.sha256(os.environ["BIRKIN_NATIVE_OWNER_TOKEN"].encode()).hexdigest())')
printf 'BIRKIN_APP_EVENT bridge-started kind=owned pid=%s executable={helper} owner_sha256=%s\\n' \
  "$bridge_pid" "$owner_digest"
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
        state = subprocess.run(
            ["/bin/ps", "-o", "state=", "-p", str(pid)],
            check=False,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if not state or state.startswith("Z"):
            continue
        if _await_process_exit(pid):
            continue
        live_pids.append(pid)
    for pid in live_pids:
        os.kill(pid, 9)
    assert live_pids == [], result.stdout + result.stderr


def test_journey_rejects_mounted_dmg_origin_for_unmounted_app(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    dist = tmp_path / "dist"
    architecture = {
        "arm64": "arm64",
        "aarch64": "arm64",
        "x86_64": "x86_64",
    }[platform.machine()]
    app = dist / "Birkin.app/Contents/MacOS/BirkinNativeApp"
    helper = (
        dist
        / "Birkin.app"
        / "Contents"
        / "Helpers"
        / architecture
        / "birkin-native-bridge"
    )
    app.parent.mkdir(parents=True)
    helper.parent.mkdir(parents=True)
    _ = helper.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    _ = app.write_text(
        """#!/bin/bash
printf '%s\n' "${BIRKIN_NATIVE_JOURNEY_ORIGIN:-missing}" \
  > "$BIRKIN_NATIVE_JOURNEY_EVIDENCE/origin-received"
exit 73
""",
        encoding="utf-8",
    )
    _ = helper.chmod(0o755)
    _ = app.chmod(0o755)

    result = subprocess.run(
        ["bash", str(SCRIPT), str(evidence), str(dist)],
        cwd=ROOT,
        env={**os.environ, "BIRKIN_NATIVE_JOURNEY_ORIGIN": "mounted-dmg"},
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 2
    assert "mounted-dmg origin requires an attached disk image" in result.stderr
    assert not (evidence / "origin-received").exists()


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
