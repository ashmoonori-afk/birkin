from __future__ import annotations

import ast
import plistlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from birkin import scheduler
from birkin.tools import desktop


_PROVIDER_PROCESS_FILES = (
    "birkin/claude_session.py",
    "birkin/codex_session.py",
    "birkin/llm.py",
    "birkin/lsp/client.py",
)


def test_provider_processes_use_portable_tree_lifecycle() -> None:
    root = Path(__file__).parents[1]
    missing: list[str] = []
    for relative in _PROVIDER_PROCESS_FILES:
        source = (root / relative).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "Popen"
            ):
                continue
            has_tree_kwargs = any(
                keyword.arg is None
                and isinstance(keyword.value, ast.Call)
                and (
                    isinstance(keyword.value.func, ast.Name)
                    and keyword.value.func.id == "popen_tree_kwargs"
                )
                for keyword in node.keywords
            )
            if not has_tree_kwargs:
                missing.append(f"{relative}:{node.lineno}")
    assert missing == []


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
    monkeypatch.setattr(desktop.sys, "platform", "linux")

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


def test_macos_window_capture_uses_native_window_handle(
    monkeypatch,
) -> None:
    calls: list[list[str]] = []
    quartz = SimpleNamespace(CGPreflightScreenCaptureAccess=lambda: True)

    def run(argv, **_kwargs):
        calls.append([str(part) for part in argv])
        Path(argv[-1]).write_bytes(b"png-data")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setitem(sys.modules, "Quartz", quartz)
    monkeypatch.setattr(desktop.subprocess, "run", run)

    data = desktop._macos_window_png(
        desktop.DesktopWindow(73, "Editor", 0, 0, 400, 300, False)
    )

    assert data == b"png-data"
    assert calls[0][1:4] == ["-x", "-l", "73"]


def test_macos_window_capture_reports_missing_permission(
    monkeypatch,
) -> None:
    quartz = SimpleNamespace(CGPreflightScreenCaptureAccess=lambda: False)
    monkeypatch.setitem(sys.modules, "Quartz", quartz)

    try:
        desktop._macos_window_png(
            desktop.DesktopWindow(73, "Editor", 0, 0, 400, 300, False)
        )
    except desktop.DesktopUnavailableError as exc:
        assert "Screen Recording" in str(exc)
    else:
        raise AssertionError("capture should require Screen Recording permission")


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
    monkeypatch.setattr(scheduler, "_macos_gui_domain", lambda: "gui/501")
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
