"""Optional backend selection without runtime side effects."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..capability_types import DisplayServer


@dataclass(frozen=True, slots=True)
class BackendSelection:
    backend_id: str
    available: bool
    refusal_code: str | None
    missing_dependencies: tuple[str, ...]


def _selection(
    backend_id: str,
    required: tuple[str, ...],
    available_modules: frozenset[str],
) -> BackendSelection:
    missing = tuple(name for name in required if name not in available_modules)
    return BackendSelection(
        backend_id=backend_id,
        available=not missing,
        refusal_code="backend_unavailable" if missing else None,
        missing_dependencies=missing,
    )


def select_backend(
    *,
    platform: str,
    display_server: DisplayServer,
    available_modules: frozenset[str],
    side_effect: Callable[[str], None] | None = None,
) -> BackendSelection:
    """Select from already available modules; never install or prompt."""
    del side_effect
    if platform == "darwin" and display_server is DisplayServer.QUARTZ:
        return _selection(
            "macos-ax-quartz",
            ("AppKit", "ApplicationServices", "Foundation", "Quartz"),
            available_modules,
        )
    if platform == "win32" and display_server is DisplayServer.WIN32:
        return _selection(
            "windows-uia",
            ("pywinauto", "win32gui", "win32process", "win32ui"),
            available_modules,
        )
    if platform == "linux" and display_server in {
        DisplayServer.X11,
        DisplayServer.XWAYLAND,
    }:
        return _selection(
            "linux-atspi-x11",
            ("Xlib", "pyatspi"),
            available_modules,
        )
    backend_id = {
        DisplayServer.WAYLAND: "linux-wayland",
        DisplayServer.UNKNOWN: "unavailable",
    }.get(display_server, "unavailable")
    return BackendSelection(
        backend_id=backend_id,
        available=False,
        refusal_code="display_backend_unsupported",
        missing_dependencies=(),
    )
