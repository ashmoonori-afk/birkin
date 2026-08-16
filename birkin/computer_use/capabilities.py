"""Pure platform capability resolution for Computer Use."""

from __future__ import annotations

from .capability_types import (
    Capability,
    CapabilityReport,
    CapabilityState,
    CapabilityStatus,
    Delivery,
    DisplayServer,
    PermissionState,
    PlatformProbe,
)


def _permission_status(
    permission: PermissionState,
    *,
    delivery: Delivery,
    verification: str,
) -> CapabilityStatus:
    if permission is PermissionState.GRANTED:
        return CapabilityStatus(
            CapabilityState.SUPPORTED,
            delivery,
            verification,
        )
    refusal = {
        PermissionState.DENIED: "permission_denied",
        PermissionState.NOT_DETERMINED: "permission_required",
        PermissionState.UNKNOWN: "permission_unknown",
        PermissionState.UNAVAILABLE: "permission_unavailable",
    }[permission]
    return CapabilityStatus(
        CapabilityState.CONDITIONAL,
        delivery,
        verification,
        refusal,
    )


def _unsupported(code: str) -> CapabilityStatus:
    return CapabilityStatus(
        CapabilityState.UNSUPPORTED,
        Delivery.NONE,
        "none",
        code,
    )


def _all_unsupported(probe: PlatformProbe, code: str) -> CapabilityReport:
    return CapabilityReport(
        probe.platform,
        probe.display_server,
        {capability: _unsupported(code) for capability in Capability},
    )


def _macos(probe: PlatformProbe) -> CapabilityReport:
    accessibility = _permission_status(
        probe.accessibility,
        delivery=Delivery.BACKGROUND,
        verification="accessibility_snapshot",
    )
    capture = _permission_status(
        probe.screen_capture,
        delivery=Delivery.BACKGROUND,
        verification="window_snapshot",
    )
    return CapabilityReport(
        probe.platform,
        probe.display_server,
        {
            Capability.LIST_APPS: CapabilityStatus(
                CapabilityState.SUPPORTED, Delivery.BACKGROUND, "process"
            ),
            Capability.LIST_WINDOWS: CapabilityStatus(
                CapabilityState.SUPPORTED,
                Delivery.BACKGROUND,
                "window_snapshot",
            ),
            Capability.CAPTURE_AX: accessibility,
            Capability.CAPTURE_VISION: capture,
            Capability.CAPTURE_SOM: CapabilityStatus(
                max(
                    accessibility.state,
                    capture.state,
                    key=lambda state: list(CapabilityState).index(state),
                ),
                Delivery.BACKGROUND,
                "accessibility_and_window_snapshot",
                accessibility.refusal_code or capture.refusal_code,
            ),
            Capability.SEMANTIC_MUTATION: accessibility,
            Capability.GLOBAL_INPUT: CapabilityStatus(
                CapabilityState.CONDITIONAL,
                Delivery.FOREGROUND,
                "fresh_target_state",
                "foreground_approval_required",
            ),
        },
    )


def _windows(probe: PlatformProbe) -> CapabilityReport:
    semantic = _permission_status(
        probe.accessibility,
        delivery=Delivery.BACKGROUND,
        verification="accessibility_snapshot",
    )
    capture = _permission_status(
        probe.screen_capture,
        delivery=Delivery.BACKGROUND,
        verification="window_snapshot",
    )
    return CapabilityReport(
        probe.platform,
        probe.display_server,
        {
            Capability.LIST_APPS: CapabilityStatus(
                CapabilityState.SUPPORTED, Delivery.BACKGROUND, "process"
            ),
            Capability.LIST_WINDOWS: CapabilityStatus(
                CapabilityState.SUPPORTED,
                Delivery.BACKGROUND,
                "window_snapshot",
            ),
            Capability.CAPTURE_AX: semantic,
            Capability.CAPTURE_VISION: capture,
            Capability.CAPTURE_SOM: CapabilityStatus(
                CapabilityState.CONDITIONAL,
                Delivery.BACKGROUND,
                "accessibility_and_window_snapshot",
            ),
            Capability.SEMANTIC_MUTATION: semantic,
            Capability.GLOBAL_INPUT: CapabilityStatus(
                CapabilityState.CONDITIONAL,
                Delivery.FOREGROUND,
                "fresh_target_state",
                "foreground_approval_required",
            ),
        },
    )


def _linux(probe: PlatformProbe) -> CapabilityReport:
    if probe.display_server is DisplayServer.WAYLAND:
        return _all_unsupported(probe, "display_backend_unsupported")
    if probe.display_server not in (DisplayServer.X11, DisplayServer.XWAYLAND):
        return _all_unsupported(probe, "backend_unavailable")
    semantic = _permission_status(
        probe.accessibility,
        delivery=Delivery.BACKGROUND,
        verification="accessibility_snapshot",
    )
    capture = _permission_status(
        probe.screen_capture,
        delivery=Delivery.BACKGROUND,
        verification="window_snapshot",
    )
    conditional = CapabilityStatus(
        CapabilityState.CONDITIONAL,
        Delivery.BACKGROUND,
        "native_identity",
    )
    return CapabilityReport(
        probe.platform,
        probe.display_server,
        {
            Capability.LIST_APPS: conditional,
            Capability.LIST_WINDOWS: conditional,
            Capability.CAPTURE_AX: semantic,
            Capability.CAPTURE_VISION: capture,
            Capability.CAPTURE_SOM: conditional,
            Capability.SEMANTIC_MUTATION: semantic,
            Capability.GLOBAL_INPUT: CapabilityStatus(
                CapabilityState.CONDITIONAL,
                Delivery.FOREGROUND,
                "fresh_target_state",
                "foreground_approval_required",
            ),
        },
    )


def capability_matrix(probe: PlatformProbe) -> CapabilityReport:
    """Resolve support without importing, installing, or prompting."""
    if not probe.interactive:
        return _all_unsupported(probe, "non_interactive_session")
    if probe.platform == "darwin":
        return _macos(probe)
    if probe.platform == "win32":
        return _windows(probe)
    if probe.platform == "linux":
        return _linux(probe)
    return _all_unsupported(probe, "backend_unavailable")
