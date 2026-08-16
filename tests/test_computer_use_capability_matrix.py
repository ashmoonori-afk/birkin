from __future__ import annotations

import pytest

from birkin.computer_use.capabilities import (
    Capability,
    CapabilityState,
    Delivery,
    DisplayServer,
    PermissionState,
    PlatformProbe,
    capability_matrix,
)


def test_macos_allows_only_semantic_background_delivery() -> None:
    report = capability_matrix(
        PlatformProbe(
            platform="darwin",
            display_server=DisplayServer.QUARTZ,
            interactive=True,
            accessibility=PermissionState.GRANTED,
            screen_capture=PermissionState.GRANTED,
        )
    )

    assert report.capabilities[Capability.CAPTURE_AX].state is (
        CapabilityState.SUPPORTED
    )
    assert report.capabilities[Capability.CAPTURE_VISION].state is (
        CapabilityState.SUPPORTED
    )
    assert report.capabilities[Capability.SEMANTIC_MUTATION].delivery is (
        Delivery.BACKGROUND
    )
    assert report.capabilities[Capability.GLOBAL_INPUT].delivery is (
        Delivery.FOREGROUND
    )


def test_native_wayland_refuses_authoritative_window_control() -> None:
    report = capability_matrix(
        PlatformProbe(
            platform="linux",
            display_server=DisplayServer.WAYLAND,
            interactive=True,
            accessibility=PermissionState.GRANTED,
            screen_capture=PermissionState.UNKNOWN,
        )
    )

    for capability in (
        Capability.LIST_WINDOWS,
        Capability.CAPTURE_VISION,
        Capability.SEMANTIC_MUTATION,
        Capability.GLOBAL_INPUT,
    ):
        item = report.capabilities[capability]
        assert item.state is CapabilityState.UNSUPPORTED
        assert item.refusal_code == "display_backend_unsupported"


@pytest.mark.parametrize(
    ("display_server", "expected"),
    [
        (DisplayServer.X11, CapabilityState.CONDITIONAL),
        (DisplayServer.XWAYLAND, CapabilityState.CONDITIONAL),
        (DisplayServer.WAYLAND, CapabilityState.UNSUPPORTED),
    ],
)
def test_linux_display_servers_remain_distinct(
    display_server: DisplayServer,
    expected: CapabilityState,
) -> None:
    report = capability_matrix(
        PlatformProbe(
            platform="linux",
            display_server=display_server,
            interactive=True,
            accessibility=PermissionState.UNKNOWN,
            screen_capture=PermissionState.UNKNOWN,
        )
    )

    assert report.capabilities[Capability.LIST_WINDOWS].state is expected


def test_noninteractive_sessions_fail_closed() -> None:
    report = capability_matrix(
        PlatformProbe(
            platform="win32",
            display_server=DisplayServer.WIN32,
            interactive=False,
            accessibility=PermissionState.UNKNOWN,
            screen_capture=PermissionState.UNKNOWN,
        )
    )

    assert all(
        item.state is CapabilityState.UNSUPPORTED
        and item.refusal_code == "non_interactive_session"
        for item in report.capabilities.values()
    )


def test_som_requires_both_ax_and_screen_capture() -> None:
    report = capability_matrix(
        PlatformProbe(
            platform="darwin",
            display_server=DisplayServer.QUARTZ,
            interactive=True,
            accessibility=PermissionState.NOT_DETERMINED,
            screen_capture=PermissionState.GRANTED,
        )
    )

    som = report.capabilities[Capability.CAPTURE_SOM]
    assert som.state is CapabilityState.CONDITIONAL
    assert som.refusal_code == "permission_required"
