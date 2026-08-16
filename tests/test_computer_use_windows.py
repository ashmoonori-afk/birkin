from __future__ import annotations

import sys

import pytest

from birkin.computer_use.backends.windows import WindowsBackend
from birkin.computer_use.capabilities import (
    DisplayServer,
    PermissionState,
)

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="Windows native backend contract",
)


def test_windows_probe_reports_interactive_uia_backend() -> None:
    backend = WindowsBackend()

    probe = backend.probe()

    assert probe.platform == "win32"
    assert probe.display_server is DisplayServer.WIN32
    assert probe.interactive is True
    assert probe.accessibility is PermissionState.GRANTED
    assert probe.responsible_process


def test_windows_discovery_uses_hwnd_and_process_generation() -> None:
    backend = WindowsBackend()

    for window in backend.list_windows(None):
        assert window.native_window_id.isdecimal()
        assert window.process_generation.startswith(f"{window.pid}:")
