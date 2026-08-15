"""Explicit setup guidance; this module performs no setup actions."""

from __future__ import annotations

import sys
from typing import Any


def setup_report(platform: str = sys.platform) -> dict[str, Any]:
    permission_actions: list[dict[str, object]] = []
    system_requirements: list[str] = []
    if platform == "darwin":
        permission_actions = [
            {
                "permission": "Accessibility",
                "settings_path": (
                    "System Settings > Privacy & Security > Accessibility"
                ),
                "automatic": False,
            },
            {
                "permission": "Screen Recording",
                "settings_path": (
                    "System Settings > Privacy & Security > Screen Recording"
                ),
                "automatic": False,
            },
        ]
    elif platform == "win32":
        system_requirements = [
            "Run in an interactive desktop session.",
            "The controller and target must have compatible integrity levels.",
        ]
    elif platform.startswith("linux"):
        system_requirements = [
            "Use X11 or XWayland with an authoritative XID mapping.",
            "Install and enable the system AT-SPI accessibility bus.",
        ]
    return {
        "ok": True,
        "platform": platform,
        "install_command": "python -m pip install 'birkin[desktop]'",
        "permission_actions": permission_actions,
        "system_requirements": system_requirements,
        "performed_actions": [],
    }
