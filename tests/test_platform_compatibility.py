from __future__ import annotations

import plistlib
import sys
from pathlib import Path
from types import SimpleNamespace

from birkin import scheduler
from birkin.tools import desktop


class _PortableWindow:
    title = "Cross-platform editor"
    left = 12
    top = 24
    right = 412
    bottom = 324
    isMinimized = False

    def getHandle(self) -> int:
        return 73


def test_desktop_windows_use_cross_platform_backend(monkeypatch) -> None:
    backend = SimpleNamespace(getAllWindows=lambda: [_PortableWindow()])
    monkeypatch.setitem(sys.modules, "pywinctl", backend)

    assert desktop._visible_windows() == [
        desktop.DesktopWindow(
            handle=73,
            title="Cross-platform editor",
            left=12,
            top=24,
            right=412,
            bottom=324,
            minimized=False,
        )
    ]


def test_macos_schedule_uses_user_launch_agent(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []

    def run(argv, **_kwargs):
        calls.append([str(part) for part in argv])
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(scheduler.sys, "platform", "darwin")
    monkeypatch.setattr(scheduler.Path, "home", classmethod(lambda _cls: tmp_path))
    monkeypatch.setattr(scheduler.subprocess, "run", run)

    assert scheduler.install_os_schedule() == 0

    agent = tmp_path / "Library" / "LaunchAgents" / "dev.birkin.daemon.plist"
    payload = plistlib.loads(agent.read_bytes())
    assert payload["Label"] == "dev.birkin.daemon"
    assert payload["ProgramArguments"] == [
        sys.executable,
        "-m",
        "birkin",
        "daemon",
    ]
    assert payload["RunAtLoad"] is True
    assert payload["KeepAlive"] is True
    assert any(call[:2] == ["launchctl", "bootstrap"] for call in calls)
    assert not any(call[0] == "crontab" for call in calls)
