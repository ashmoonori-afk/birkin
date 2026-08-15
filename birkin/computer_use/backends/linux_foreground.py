"""Approved XTest fallback bound to current AT-SPI element geometry."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from ..models import MutationCommand
from .base import BackendError
from .linux_atspi import LinuxATSPi


def mutate(
    display: Any,
    atspi: LinuxATSPi,
    command: MutationCommand,
) -> bool:
    start_bounds = atspi.bounds(command.accessibility_identity)
    if start_bounds is None:
        raise BackendError("stale_ref", "The AT-SPI element bounds changed.")
    start = _center(start_bounds)
    xlib = import_module("Xlib.X")
    xtest = import_module("Xlib.ext.xtest")
    if command.action == "scroll":
        _scroll(display, xtest, xlib, command, start)
        return True
    button = {
        "click": 1,
        "double_click": 1,
        "right_click": 3,
        "middle_click": 2,
        "drag": 1,
    }[command.action]
    end = _drag_end(atspi, command, start)
    xtest.fake_input(
        display,
        xlib.MotionNotify,
        x=start[0],
        y=start[1],
    )
    repetitions = 2 if command.action == "double_click" else 1
    for _ in range(repetitions):
        xtest.fake_input(display, xlib.ButtonPress, button)
        if command.action == "drag":
            xtest.fake_input(
                display,
                xlib.MotionNotify,
                x=end[0],
                y=end[1],
            )
        xtest.fake_input(display, xlib.ButtonRelease, button)
    display.sync()
    return True


def release_inputs(display: Any) -> tuple[str, ...]:
    xlib = import_module("Xlib.X")
    xtest = import_module("Xlib.ext.xtest")
    released: list[str] = []
    for name, button in (
        ("mouse_left", 1),
        ("mouse_middle", 2),
        ("mouse_right", 3),
    ):
        xtest.fake_input(display, xlib.ButtonRelease, button)
        released.append(name)
    display.sync()
    return tuple(released)


def _scroll(
    display: Any,
    xtest: Any,
    xlib: Any,
    command: MutationCommand,
    start: tuple[int, int],
) -> None:
    amount = max(1, min(100, int(command.amount or 1)))
    button = (
        6
        if command.axis == "horizontal" and command.value == "negative"
        else 7
        if command.axis == "horizontal"
        else 4
        if command.value == "positive"
        else 5
    )
    xtest.fake_input(
        display,
        xlib.MotionNotify,
        x=start[0],
        y=start[1],
    )
    for _ in range(amount):
        xtest.fake_input(display, xlib.ButtonPress, button)
        xtest.fake_input(display, xlib.ButtonRelease, button)
    display.sync()


def _drag_end(
    atspi: LinuxATSPi,
    command: MutationCommand,
    start: tuple[int, int],
) -> tuple[int, int]:
    if command.action != "drag":
        return start
    end_bounds = atspi.bounds(command.secondary_accessibility_identity or "")
    if end_bounds is None:
        raise BackendError(
            "stale_ref",
            "The AT-SPI drag destination changed.",
        )
    return _center(end_bounds)


def _center(bounds: tuple[int, int, int, int]) -> tuple[int, int]:
    left, top, right, bottom = bounds
    return (round((left + right) / 2), round((top + bottom) / 2))
