"""Approved Win32 pointer fallback bound to current UIA rectangles."""

from __future__ import annotations

from typing import Any

from ..models import MutationCommand
from .base import BackendError


def release_inputs(mouse: Any) -> tuple[str, ...]:
    del mouse
    return ()


def mutate(
    mouse: Any,
    win32gui: Any,
    elements: dict[str, Any],
    wrapper: Any,
    command: MutationCommand,
) -> bool:
    rectangle = wrapper.rectangle()
    start = (
        int((rectangle.left + rectangle.right) / 2),
        int((rectangle.top + rectangle.bottom) / 2),
    )
    try:
        topmost = win32gui.GetAncestor(win32gui.WindowFromPoint(start), 2)
        expected = int(wrapper.top_level_parent().handle)
    except (AttributeError, OSError, RuntimeError, ValueError) as exc:
        raise BackendError(
            "foreground_delivery_unsupported",
            "Win32 could not prove the topmost target window.",
        ) from exc
    if int(topmost) != expected:
        raise BackendError(
            "foreground_delivery_unsupported",
            "The bound UIA window is occluded at the target point.",
        )
    if command.action == "scroll":
        if command.axis != "vertical":
            raise BackendError(
                "foreground_delivery_unsupported",
                "Win32 foreground scrolling supports only the vertical axis.",
            )
        distance = max(1, min(100, int(command.amount or 1)))
        if command.value == "negative":
            distance = -distance
        mouse.scroll(coords=start, wheel_dist=distance)
        return True
    button = {
        "click": "left",
        "double_click": "left",
        "right_click": "right",
        "middle_click": "middle",
        "drag": "left",
    }[command.action]
    if command.action == "drag":
        secondary = elements.get(command.secondary_accessibility_identity or "")
        if secondary is None:
            raise BackendError(
                "stale_ref",
                "The UIA drag destination changed.",
            )
        destination = secondary.rectangle()
        end = (
            int((destination.left + destination.right) / 2),
            int((destination.top + destination.bottom) / 2),
        )
        mouse.move(coords=start)
        mouse.press(button=button, coords=start)
        try:
            mouse.move(coords=end)
        finally:
            mouse.release(button=button, coords=end)
        return True
    if command.action == "double_click":
        mouse.double_click(button=button, coords=start)
    else:
        mouse.click(button=button, coords=start)
    return True
