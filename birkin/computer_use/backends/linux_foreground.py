"""Approved XTest fallback bound to current AT-SPI element geometry."""

from __future__ import annotations

from importlib import import_module
from typing import Any, Protocol

from ..models import MutationCommand
from .base import BackendError


class _WindowResolver(Protocol):
    def bounds(self, identity: str) -> tuple[int, int, int, int] | None: ...

    def window_id(self, identity: str) -> str | None: ...


def mutate(
    display: Any,
    atspi: _WindowResolver,
    command: MutationCommand,
) -> bool:
    start_bounds = atspi.bounds(command.accessibility_identity)
    if start_bounds is None:
        raise BackendError("stale_ref", "The AT-SPI element bounds changed.")
    start = _center(start_bounds)
    xlib = import_module("Xlib.X")
    xerror = import_module("Xlib.error")
    xtest = import_module("Xlib.ext.xtest")
    try:
        _require_topmost(display, atspi, command, start, xlib)
    except (AttributeError, RuntimeError, xerror.XError) as exc:
        raise BackendError(
            "foreground_delivery_unsupported",
            "X11 could not prove the topmost target window.",
        ) from exc
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
        try:
            if command.action == "drag":
                xtest.fake_input(
                    display,
                    xlib.MotionNotify,
                    x=end[0],
                    y=end[1],
                )
        finally:
            xtest.fake_input(display, xlib.ButtonRelease, button)
    display.sync()
    return True


def release_inputs(display: Any) -> tuple[str, ...]:
    del display
    return ()


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
    atspi: _WindowResolver,
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


def _require_topmost(
    display: Any,
    atspi: _WindowResolver,
    command: MutationCommand,
    point: tuple[int, int],
    xlib: Any,
) -> None:
    raw_expected = atspi.window_id(command.accessibility_identity)
    if raw_expected is None:
        raise BackendError("stale_ref", "The AT-SPI window binding changed.")
    root = display.screen().root
    expected = display.create_resource_object("window", int(raw_expected))
    expected_root_child = _root_child(expected, root)
    for child in reversed(root.query_tree().children):
        try:
            attributes = child.get_attributes()
            if attributes.map_state != xlib.IsViewable:
                continue
            geometry = child.get_geometry()
            translated = child.translate_coords(root, 0, 0)
        except (AttributeError, RuntimeError):
            continue
        if (
            translated.x <= point[0] < translated.x + geometry.width
            and translated.y <= point[1] < translated.y + geometry.height
        ):
            if child.id != expected_root_child.id:
                raise BackendError(
                    "foreground_delivery_unsupported",
                    "The bound X11 window is occluded at the target point.",
                )
            return
    raise BackendError(
        "foreground_delivery_unsupported",
        "No authoritative topmost X11 window exists at the target point.",
    )


def _root_child(window: Any, root: Any) -> Any:
    current = window
    while True:
        parent = current.query_tree().parent
        if parent.id == root.id:
            return current
        current = parent


def _center(bounds: tuple[int, int, int, int]) -> tuple[int, int]:
    left, top, right, bottom = bounds
    return (round((left + right) / 2), round((top + bottom) / 2))
