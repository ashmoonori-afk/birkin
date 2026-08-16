"""Native Linux X11 discovery/capture with honest Wayland refusal."""

from __future__ import annotations

import os
import sys
from importlib import import_module
from importlib.util import find_spec
from typing import Any

from ..capability_types import DisplayServer, PermissionState, PlatformProbe
from ..models import (
    BackendCapture,
    FocusSnapshot,
    MutationCommand,
    ObservedApp,
    ObservedElement,
    ObservedWindow,
)
from . import linux_foreground
from .base import BackendError
from .linux_atspi import LinuxATSPi
from .linux_native import (
    exact_window_png,
    process_generation,
    property_int,
    window_title,
)


class LinuxBackend:
    backend_id = "linux-atspi-x11"
    foreground_actions = frozenset(
        {
            "click",
            "double_click",
            "right_click",
            "middle_click",
            "drag",
            "scroll",
        }
    )

    def __init__(self) -> None:
        if not sys.platform.startswith("linux"):
            raise BackendError("backend_unavailable", "Linux is required.")
        self.display_server: DisplayServer = (
            DisplayServer.WAYLAND
            if os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY")
            else DisplayServer.XWAYLAND
            if os.environ.get("WAYLAND_DISPLAY") and os.environ.get("DISPLAY")
            else DisplayServer.X11
            if os.environ.get("DISPLAY")
            else DisplayServer.UNKNOWN
        )
        self._display: Any = None
        self.atspi: LinuxATSPi | None = None
        self._window_epochs: dict[
            int,
            tuple[int, tuple[object, ...], bool],
        ] = {}
        if find_spec("pyatspi") is not None:
            pyatspi = import_module("pyatspi")
            self.atspi = LinuxATSPi(pyatspi)
        if self.display_server in {DisplayServer.X11, DisplayServer.XWAYLAND}:
            try:
                display_module = import_module("Xlib.display")
                self._display = display_module.Display()
            except (ImportError, OSError):
                self._display = None

    def probe(self) -> PlatformProbe:
        atspi = find_spec("pyatspi") is not None
        return PlatformProbe(
            platform="linux",
            display_server=self.display_server,
            interactive=self.display_server is not DisplayServer.UNKNOWN,
            accessibility=(
                PermissionState.GRANTED if atspi else PermissionState.UNAVAILABLE
            ),
            screen_capture=(
                PermissionState.GRANTED
                if self._display is not None
                else PermissionState.UNAVAILABLE
            ),
            responsible_process=sys.executable,
        )

    def list_apps(self) -> tuple[ObservedApp, ...]:
        apps: dict[int, ObservedApp] = {}
        for window in self.list_windows(None):
            try:
                import psutil
            except ImportError:
                continue
            try:
                process = psutil.Process(window.pid)
                identity = process.exe()
                name = process.name()
            except psutil.Error:
                continue
            apps[window.pid] = ObservedApp(
                window.pid,
                window.process_generation,
                identity,
                name,
            )
        return tuple(apps.values())

    def list_windows(
        self,
        app: ObservedApp | None,
    ) -> tuple[ObservedWindow, ...]:
        if self._display is None:
            return ()
        xlib = import_module("Xlib.X")

        root = self._display.screen().root
        client_atom = self._display.intern_atom("_NET_CLIENT_LIST")
        clients = root.get_full_property(
            client_atom,
            xlib.AnyPropertyType,
        )
        if clients is None:
            return ()
        windows: list[ObservedWindow] = []
        active_xids: set[int] = set()
        for xid in clients.value:
            native_xid = int(xid)
            active_xids.add(native_xid)
            window = self._display.create_resource_object("window", native_xid)
            pid = property_int(self._display, window, "_NET_WM_PID")
            if pid is None:
                continue
            generation = process_generation(pid)
            geometry = window.get_geometry()
            translated = window.translate_coords(root, 0, 0)
            title = window_title(self._display, window)
            bounds = (
                translated.x,
                translated.y,
                translated.x + geometry.width,
                translated.y + geometry.height,
            )
            window_generation = self._window_generation(
                native_xid,
                (pid, generation, title, bounds),
            )
            if app is not None and (
                pid != app.pid or generation != app.process_generation
            ):
                continue
            windows.append(
                ObservedWindow(
                    pid=pid,
                    process_generation=generation,
                    native_window_id=str(native_xid),
                    window_generation=window_generation,
                    title=title,
                    bounds=bounds,
                )
            )
        for xid, (epoch, signature, active) in tuple(self._window_epochs.items()):
            if xid not in active_xids and active:
                self._window_epochs[xid] = (epoch, signature, False)
        return tuple(windows)

    def _window_generation(
        self,
        xid: int,
        signature: tuple[object, ...],
    ) -> int:
        previous = self._window_epochs.get(xid)
        if previous is None:
            epoch = 1
        else:
            previous_epoch, previous_signature, was_active = previous
            epoch = (
                previous_epoch
                if was_active and previous_signature == signature
                else previous_epoch + 1
            )
        self._window_epochs[xid] = (epoch, signature, True)
        return epoch

    def capture(
        self,
        window: ObservedWindow,
        mode: str,
    ) -> BackendCapture:
        elements: tuple[ObservedElement, ...] = ()
        if mode in {"ax", "som"}:
            if self.atspi is None:
                raise BackendError(
                    "permission_unavailable",
                    "The system AT-SPI adapter is unavailable.",
                )
            elements = self.atspi.capture(window)
        if mode in {"vision", "som"} and self._display is None:
            raise BackendError(
                "capture_isolation_unavailable",
                "An authoritative X11 display is unavailable.",
            )
        data = None
        width = height = None
        if mode in {"vision", "som"}:
            data, width, height = exact_window_png(
                self._display,
                window.native_window_id,
            )
        return BackendCapture(
            ui_fingerprint=(
                process_generation(window.pid) + f":{len(data or b'')}:{len(elements)}"
            ),
            elements=elements,
            image_bytes=data,
            media_type="image/png" if data is not None else None,
            width=width,
            height=height,
            isolated=True,
        )

    def mutate(self, command: MutationCommand) -> bool:
        if self.atspi is None:
            raise BackendError(
                "permission_unavailable",
                "The system AT-SPI adapter is unavailable.",
            )
        if command.delivery == "foreground":
            return self._foreground_mutate(command)
        return self.atspi.mutate(command)

    def read_element(
        self,
        accessibility_identity: str,
    ) -> ObservedElement | None:
        return (
            self.atspi.read(accessibility_identity) if self.atspi is not None else None
        )

    def focus_state(self) -> FocusSnapshot:
        if self._display is None:
            return FocusSnapshot(None, None, None, None)
        focus = self._display.get_input_focus().focus
        pointer = self._display.screen().root.query_pointer()
        return FocusSnapshot(
            None,
            str(getattr(focus, "id", "")) or None,
            (pointer.root_x, pointer.root_y),
            None,
        )

    def can_restore_focus(self, snapshot: FocusSnapshot) -> bool:
        return self._display is not None and snapshot.focused_window_id is not None

    def restore_focus(self, snapshot: FocusSnapshot) -> bool:
        if not self.can_restore_focus(snapshot):
            return False
        xlib = import_module("Xlib.X")

        window = self._display.create_resource_object(
            "window",
            int(snapshot.focused_window_id or "0"),
        )
        window.set_input_focus(xlib.RevertToParent, xlib.CurrentTime)
        if snapshot.pointer is not None:
            self._display.screen().root.warp_pointer(
                snapshot.pointer[0],
                snapshot.pointer[1],
            )
        self._display.sync()
        return True

    def release_inputs(self) -> tuple[str, ...]:
        if self._display is None:
            return ()
        return linux_foreground.release_inputs(self._display)

    def _foreground_mutate(self, command: MutationCommand) -> bool:
        if self._display is None or self.atspi is None:
            raise BackendError(
                "foreground_delivery_unsupported",
                "X11 and AT-SPI are required for foreground delivery.",
            )
        return linux_foreground.mutate(self._display, self.atspi, command)
