from __future__ import annotations

from birkin.computer_use.capabilities import (
    DisplayServer,
    PermissionState,
    PlatformProbe,
)
from birkin.computer_use.doctor import doctor_report


def test_doctor_keeps_unknown_denied_and_unsupported_distinct() -> None:
    report = doctor_report(
        PlatformProbe(
            platform="darwin",
            display_server=DisplayServer.QUARTZ,
            interactive=True,
            accessibility=PermissionState.DENIED,
            screen_capture=PermissionState.UNKNOWN,
            responsible_process="org.example.BirkinQA",
        )
    )

    assert report["schema_version"] == "1"
    assert report["permissions"] == {
        "accessibility": "denied",
        "screen_capture": "unknown",
    }
    assert report["capabilities"]["capture_ax"]["refusal_code"] == ("permission_denied")
    assert report["capabilities"]["capture_vision"]["refusal_code"] == (
        "permission_unknown"
    )


def test_doctor_guidance_is_capability_scoped_and_non_prompting() -> None:
    report = doctor_report(
        PlatformProbe(
            platform="darwin",
            display_server=DisplayServer.QUARTZ,
            interactive=True,
            accessibility=PermissionState.DENIED,
            screen_capture=PermissionState.GRANTED,
            responsible_process="org.example.BirkinQA",
        )
    )

    guidance = report["guidance"]
    assert guidance == [
        {
            "capability": "capture_ax",
            "permission": "accessibility",
            "responsible_process": "org.example.BirkinQA",
            "settings_path": ("System Settings > Privacy & Security > Accessibility"),
        },
        {
            "capability": "semantic_mutation",
            "permission": "accessibility",
            "responsible_process": "org.example.BirkinQA",
            "settings_path": ("System Settings > Privacy & Security > Accessibility"),
        },
    ]
    assert report["permission_prompted"] is False
