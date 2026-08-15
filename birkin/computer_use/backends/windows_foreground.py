"""Approved Win32 pointer fallback bound to current UIA rectangles."""

from __future__ import annotations

from typing import Any

from ..models import MutationCommand
from .base import BackendError


def release_inputs(mouse: Any) -> tuple[str, ...]:
    released: list[str] = []
    for button in ("left", "right", "middle"):
        try:
            mouse.release(button=button)
            released.append(f"mouse_{button}")
        except (OSError, RuntimeError, ValueError):
            continue
    return tuple(released)


def mutate(
    mouse: Any,
    elements: dict[str, Any],
    wrapper: Any,
    command: MutationCommand,
) -> bool:
    rectangle = wrapper.rectangle()
    start = (
        int((rectangle.left + rectangle.right) / 2),
        int((rectangle.top + rectangle.bottom) / 2),
    )
    if command.action == "scroll":
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
        mouse.move(coords=end)
        mouse.release(button=button, coords=end)
        return True
    mouse.click(
        button=button,
        coords=start,
        double=command.action == "double_click",
    )
    return True
