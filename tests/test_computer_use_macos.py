from __future__ import annotations

import sys

import pytest

from birkin.computer_use.backends.base import BackendError
from birkin.computer_use.backends.macos import MacOSBackend
from birkin.computer_use.capabilities import (
    DisplayServer,
    PermissionState,
)
from birkin.computer_use.models import ObservedWindow

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="macOS native backend contract",
)


def test_macos_probe_is_non_prompting_and_capability_specific() -> None:
    backend = MacOSBackend()

    probe = backend.probe()

    assert probe.platform == "darwin"
    assert probe.display_server is DisplayServer.QUARTZ
    assert probe.screen_capture in {
        PermissionState.GRANTED,
        PermissionState.NOT_DETERMINED,
    }
    assert probe.accessibility in {
        PermissionState.GRANTED,
        PermissionState.NOT_DETERMINED,
    }
    assert probe.responsible_process


def test_macos_discovery_binds_pid_process_generation_and_cgwindow() -> None:
    backend = MacOSBackend()

    apps = backend.list_apps()
    windows = backend.list_windows(None)

    assert apps
    assert all(app.pid > 0 and app.process_generation for app in apps)
    assert all(
        window.pid > 0
        and window.process_generation
        and window.native_window_id.isdecimal()
        and window.window_generation > 0
        for window in windows
    )


def test_macos_ax_capture_refuses_when_accessibility_is_unavailable() -> None:
    backend = MacOSBackend()
    if backend.probe().accessibility is PermissionState.GRANTED:
        pytest.skip("Accessibility is granted; denial path is not observable")
    window = ObservedWindow(
        pid=1,
        process_generation="fixture",
        native_window_id="1",
        window_generation=1,
        title="Fixture",
        bounds=(0, 0, 100, 100),
    )

    with pytest.raises(BackendError) as exc_info:
        backend.capture(window, "ax")

    assert exc_info.value.code == "permission_required"
