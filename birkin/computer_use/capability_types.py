"""Typed platform capability records."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal


class DisplayServer(str, Enum):
    QUARTZ = "quartz"
    WIN32 = "win32"
    X11 = "x11"
    XWAYLAND = "xwayland"
    WAYLAND = "wayland"
    UNKNOWN = "unknown"


class PermissionState(str, Enum):
    GRANTED = "granted"
    DENIED = "denied"
    NOT_DETERMINED = "not_determined"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


class Capability(str, Enum):
    LIST_APPS = "list_apps"
    LIST_WINDOWS = "list_windows"
    CAPTURE_AX = "capture_ax"
    CAPTURE_VISION = "capture_vision"
    CAPTURE_SOM = "capture_som"
    SEMANTIC_MUTATION = "semantic_mutation"
    GLOBAL_INPUT = "global_input"


class CapabilityState(str, Enum):
    SUPPORTED = "supported"
    CONDITIONAL = "conditional"
    UNSUPPORTED = "unsupported"


class Delivery(str, Enum):
    BACKGROUND = "background"
    FOREGROUND = "foreground"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class PlatformProbe:
    platform: Literal["darwin", "win32", "linux"] | str
    display_server: DisplayServer
    interactive: bool
    accessibility: PermissionState
    screen_capture: PermissionState
    responsible_process: str = ""


@dataclass(frozen=True, slots=True)
class CapabilityStatus:
    state: CapabilityState
    delivery: Delivery
    verification: str
    refusal_code: str | None = None


@dataclass(frozen=True, slots=True)
class CapabilityReport:
    platform: str
    display_server: DisplayServer
    capabilities: dict[Capability, CapabilityStatus]
