"""Approved Quartz fallback bound to current AX element geometry."""

from __future__ import annotations

from typing import Any, Protocol

from ..models import MutationCommand
from .base import BackendError


class _BoundsResolver(Protocol):
    def bounds(self, identity: str) -> tuple[int, int, int, int] | None: ...


def release_inputs(quartz: Any) -> tuple[str, ...]:
    event = quartz.CGEventCreate(None)
    point = quartz.CGEventGetLocation(event)
    released: list[str] = []
    for name, event_type, button in (
        (
            "mouse_left",
            quartz.kCGEventLeftMouseUp,
            quartz.kCGMouseButtonLeft,
        ),
        (
            "mouse_right",
            quartz.kCGEventRightMouseUp,
            quartz.kCGMouseButtonRight,
        ),
        (
            "mouse_middle",
            quartz.kCGEventOtherMouseUp,
            quartz.kCGMouseButtonCenter,
        ),
    ):
        mouse_up = quartz.CGEventCreateMouseEvent(
            None,
            event_type,
            point,
            button,
        )
        quartz.CGEventPost(quartz.kCGHIDEventTap, mouse_up)
        released.append(name)
    return tuple(released)


def mutate(
    quartz: Any,
    resolver: _BoundsResolver,
    command: MutationCommand,
) -> bool:
    bounds = resolver.bounds(command.accessibility_identity)
    if bounds is None:
        raise BackendError("stale_ref", "The AX element bounds changed.")
    start = _center(bounds)
    end = _drag_end(resolver, command, start)
    if command.action == "scroll":
        amount = max(1, min(100, int(command.amount or 1)))
        delta = amount if command.value == "positive" else -amount
        event = quartz.CGEventCreateScrollWheelEvent(
            None,
            quartz.kCGScrollEventUnitPixel,
            1,
            delta,
        )
        quartz.CGEventPost(quartz.kCGHIDEventTap, event)
        return True
    button, down, up = {
        "click": (
            quartz.kCGMouseButtonLeft,
            quartz.kCGEventLeftMouseDown,
            quartz.kCGEventLeftMouseUp,
        ),
        "double_click": (
            quartz.kCGMouseButtonLeft,
            quartz.kCGEventLeftMouseDown,
            quartz.kCGEventLeftMouseUp,
        ),
        "right_click": (
            quartz.kCGMouseButtonRight,
            quartz.kCGEventRightMouseDown,
            quartz.kCGEventRightMouseUp,
        ),
        "middle_click": (
            quartz.kCGMouseButtonCenter,
            quartz.kCGEventOtherMouseDown,
            quartz.kCGEventOtherMouseUp,
        ),
        "drag": (
            quartz.kCGMouseButtonLeft,
            quartz.kCGEventLeftMouseDown,
            quartz.kCGEventLeftMouseUp,
        ),
    }[command.action]
    repetitions = 2 if command.action == "double_click" else 1
    for click_count in range(1, repetitions + 1):
        down_event = quartz.CGEventCreateMouseEvent(
            None,
            down,
            start,
            button,
        )
        up_event = quartz.CGEventCreateMouseEvent(
            None,
            up,
            end,
            button,
        )
        if repetitions == 2:
            quartz.CGEventSetIntegerValueField(
                down_event,
                quartz.kCGMouseEventClickState,
                click_count,
            )
            quartz.CGEventSetIntegerValueField(
                up_event,
                quartz.kCGMouseEventClickState,
                click_count,
            )
        quartz.CGEventPost(quartz.kCGHIDEventTap, down_event)
        if command.action == "drag":
            drag_event = quartz.CGEventCreateMouseEvent(
                None,
                quartz.kCGEventLeftMouseDragged,
                end,
                button,
            )
            quartz.CGEventPost(quartz.kCGHIDEventTap, drag_event)
        quartz.CGEventPost(quartz.kCGHIDEventTap, up_event)
    return True


def _drag_end(
    resolver: _BoundsResolver,
    command: MutationCommand,
    start: tuple[float, float],
) -> tuple[float, float]:
    if command.action != "drag":
        return start
    end_bounds = resolver.bounds(command.secondary_accessibility_identity or "")
    if end_bounds is None:
        raise BackendError("stale_ref", "The AX drag destination changed.")
    return _center(end_bounds)


def _center(bounds: tuple[int, int, int, int]) -> tuple[float, float]:
    left, top, right, bottom = bounds
    return ((left + right) / 2, (top + bottom) / 2)
