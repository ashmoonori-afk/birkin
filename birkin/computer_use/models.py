"""Shared immutable Computer Use value objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CaptureMode = Literal["ax", "vision", "som"]
DeliveryMode = Literal["background", "foreground"]


@dataclass(frozen=True, slots=True)
class ElementTarget:
    """Opaque authority supplied for an element mutation."""

    app_ref: str
    window_ref: str
    snapshot_ref: str
    element_ref: str


@dataclass(frozen=True, slots=True)
class SnapshotReference:
    token: str
    snapshot_generation: int
    mode: CaptureMode


@dataclass(frozen=True, slots=True)
class ObservedApp:
    pid: int
    process_generation: str
    native_identity: str
    name: str


@dataclass(frozen=True, slots=True)
class ObservedWindow:
    pid: int
    process_generation: str
    native_window_id: str
    window_generation: int
    title: str
    bounds: tuple[int, int, int, int]
    minimized: bool = False


@dataclass(frozen=True, slots=True)
class ObservedElement:
    accessibility_identity: str
    accessibility_path: tuple[str, ...]
    role: str
    name: str
    value: object | None
    supported_actions: frozenset[str]
    sensitive_category: str | None = None


@dataclass(frozen=True, slots=True)
class BackendCapture:
    ui_fingerprint: str
    elements: tuple[ObservedElement, ...]
    image_bytes: bytes | None
    media_type: str | None
    width: int | None
    height: int | None
    isolated: bool


@dataclass(frozen=True, slots=True)
class MutationCommand:
    action: str
    accessibility_identity: str
    delivery: DeliveryMode
    value: object | None = None
    mode: str | None = None
    secondary_accessibility_identity: str | None = None
    modifiers: tuple[str, ...] = ()
    axis: str | None = None
    amount: float | None = None


@dataclass(frozen=True, slots=True)
class FocusSnapshot:
    frontmost_pid: int | None
    focused_window_id: str | None
    pointer: tuple[int, int] | None
    space_id: str | None

    def focus_equivalent(self, other: FocusSnapshot) -> bool:
        """Compare desktop focus authority without treating pointer motion as focus."""
        return (
            self.frontmost_pid == other.frontmost_pid
            and self.focused_window_id == other.focused_window_id
            and self.space_id == other.space_id
        )
