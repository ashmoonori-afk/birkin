from __future__ import annotations

import os
import sys

import pytest

from birkin.computer_use.backends.linux import LinuxBackend
from birkin.computer_use.capabilities import DisplayServer

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="Linux native backend contract",
)


def test_linux_probe_keeps_wayland_and_x11_distinct() -> None:
    backend = LinuxBackend()

    probe = backend.probe()

    if os.environ.get("WAYLAND_DISPLAY"):
        assert probe.display_server is DisplayServer.WAYLAND
    elif os.environ.get("DISPLAY"):
        assert probe.display_server is DisplayServer.X11
    else:
        assert probe.display_server is DisplayServer.UNKNOWN


def test_linux_native_wayland_refuses_exact_window_discovery(
    monkeypatch,
) -> None:
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.delenv("DISPLAY", raising=False)
    backend = LinuxBackend()

    assert backend.list_windows(None) == ()
