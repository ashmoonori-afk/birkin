"""Read-only Computer Use doctor reports."""

from __future__ import annotations

from typing import Any

from .capabilities import capability_matrix
from .capability_types import (
    Capability,
    CapabilityReport,
    PlatformProbe,
)


def _capabilities(report: CapabilityReport) -> dict[str, dict[str, Any]]:
    return {
        capability.value: {
            "state": status.state.value,
            "delivery": status.delivery.value,
            "verification": status.verification,
            "refusal_code": status.refusal_code,
        }
        for capability, status in report.capabilities.items()
    }


def _macos_guidance(
    probe: PlatformProbe,
    report: CapabilityReport,
) -> list[dict[str, str]]:
    guidance: list[dict[str, str]] = []
    paths = {
        Capability.CAPTURE_AX: (
            "accessibility",
            "System Settings > Privacy & Security > Accessibility",
        ),
        Capability.SEMANTIC_MUTATION: (
            "accessibility",
            "System Settings > Privacy & Security > Accessibility",
        ),
        Capability.CAPTURE_VISION: (
            "screen_capture",
            "System Settings > Privacy & Security > Screen Recording",
        ),
    }
    for capability, (permission, settings_path) in paths.items():
        status = report.capabilities[capability]
        if status.refusal_code not in {
            "permission_denied",
            "permission_required",
        }:
            continue
        guidance.append(
            {
                "capability": capability.value,
                "permission": permission,
                "responsible_process": probe.responsible_process,
                "settings_path": settings_path,
            }
        )
    return guidance


def doctor_report(probe: PlatformProbe) -> dict[str, Any]:
    """Return a stable report and never request a permission prompt."""
    report = capability_matrix(probe)
    guidance = _macos_guidance(probe, report) if probe.platform == "darwin" else []
    return {
        "schema_version": "1",
        "platform": probe.platform,
        "display_server": probe.display_server.value,
        "interactive": probe.interactive,
        "responsible_process": probe.responsible_process,
        "permissions": {
            "accessibility": probe.accessibility.value,
            "screen_capture": probe.screen_capture.value,
        },
        "capabilities": _capabilities(report),
        "guidance": guidance,
        "permission_prompted": False,
    }
