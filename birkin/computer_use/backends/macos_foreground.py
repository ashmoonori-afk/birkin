"""Approved Quartz fallback bound to current AX element geometry."""

from __future__ import annotations

from typing import Any, Protocol

from ..models import MutationCommand
from .base import BackendError


class _BoundsResolver(Protocol):
    def bounds(self, identity: str) -> tuple[int, int, int, int] | None: ...

    def window_id(self, identity: str) -> str | None: ...


def release_inputs(quartz: Any) -> tuple[str, ...]:
    del quartz
    return ()


def mutate(
    quartz: Any,
    resolver: _BoundsResolver,
    command: MutationCommand,
) -> bool:
    bounds = resolver.bounds(command.accessibility_identity)
    if bounds is None:
        raise BackendError("stale_ref", "The AX element bounds changed.")
    start = _center(bounds)
    _require_topmost(quartz, resolver, command, start)
    end = _drag_end(resolver, command, start)
    if command.action == "scroll":
        if command.axis != "vertical":
            raise BackendError(
                "foreground_delivery_unsupported",
                "Quartz foreground scrolling supports only the vertical axis.",
            )
        amount = max(1, min(100, int(command.amount or 1)))
        delta = amount if command.value == "positive" else -amount
        quartz.CGWarpMouseCursorPosition(start)
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
        try:
            if command.action == "drag":
                drag_event = quartz.CGEventCreateMouseEvent(
                    None,
                    quartz.kCGEventLeftMouseDragged,
                    end,
                    button,
                )
                quartz.CGEventPost(quartz.kCGHIDEventTap, drag_event)
        finally:
            quartz.CGEventPost(quartz.kCGHIDEventTap, up_event)
    return True


def _require_topmost(
    quartz: Any,
    resolver: _BoundsResolver,
    command: MutationCommand,
    point: tuple[float, float],
) -> None:
    expected = resolver.window_id(command.accessibility_identity)
    if expected is None:
        raise BackendError("stale_ref", "The AX window binding changed.")
    options = (
        quartz.kCGWindowListOptionOnScreenOnly
        | quartz.kCGWindowListExcludeDesktopElements
    )
    windows = (
        quartz.CGWindowListCopyWindowInfo(
            options,
            quartz.kCGNullWindowID,
        )
        or ()
    )
    for raw in windows:
        bounds = raw.get(quartz.kCGWindowBounds, {})
        left = float(bounds.get("X", 0))
        top = float(bounds.get("Y", 0))
        right = left + float(bounds.get("Width", 0))
        bottom = top + float(bounds.get("Height", 0))
        if left <= point[0] < right and top <= point[1] < bottom:
            if str(int(raw[quartz.kCGWindowNumber])) != expected:
                raise BackendError(
                    "foreground_delivery_unsupported",
                    "The bound AX window is occluded at the target point.",
                )
            return
    raise BackendError(
        "foreground_delivery_unsupported",
        "No authoritative topmost window exists at the target point.",
    )


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
