"""Native macOS AX and Quartz backend."""

from __future__ import annotations

import sys
from importlib import import_module
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
from . import macos_foreground
from .base import BackendError
from .macos_ax import MacOSAX
from .macos_native import (
    capture_fingerprint,
    observed_app,
    process_generation,
    raw_windows,
    resolve_window,
    window_png,
)


class MacOSBackend:
    backend_id = "macos-ax-quartz"
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
        if sys.platform != "darwin":
            raise BackendError("backend_unavailable", "macOS is required.")
        try:
            application_services = import_module("ApplicationServices")
            quartz = import_module("Quartz")
            appkit = import_module("AppKit")
            foundation = import_module("Foundation")
        except ImportError as exc:
            raise BackendError(
                "backend_unavailable",
                "The macOS desktop optional dependencies are not installed.",
            ) from exc
        self.api: Any = application_services
        self.quartz: Any = quartz
        self.running_application: Any = appkit.NSRunningApplication
        self.workspace: Any = appkit.NSWorkspace
        self.event: Any = appkit.NSEvent
        self.activate_ignoring_other_apps = (
            appkit.NSApplicationActivateIgnoringOtherApps
        )
        self.mutable_data: Any = foundation.NSMutableData
        self.bundle: Any = foundation.NSBundle
        self.ax = MacOSAX(application_services)
        self._window_epochs: dict[tuple[int, str], int] = {}
        self._missing_windows: set[tuple[int, str]] = set()

    def probe(self) -> PlatformProbe:
        session = self.quartz.CGSessionCopyCurrentDictionary()
        bundle_id = self.bundle.mainBundle().bundleIdentifier()
        responsible = f"{bundle_id or 'unbundled'} ({sys.executable})"
        return PlatformProbe(
            platform="darwin",
            display_server=DisplayServer.QUARTZ,
            interactive=bool(session),
            accessibility=(
                PermissionState.GRANTED
                if self.ax.trusted()
                else PermissionState.NOT_DETERMINED
            ),
            screen_capture=(
                PermissionState.GRANTED
                if self.quartz.CGPreflightScreenCaptureAccess()
                else PermissionState.NOT_DETERMINED
            ),
            responsible_process=responsible,
        )

    def list_apps(self) -> tuple[ObservedApp, ...]:
        apps: dict[int, ObservedApp] = {}
        for raw in raw_windows(self.quartz):
            pid = int(raw[self.quartz.kCGWindowOwnerPID])
            app = observed_app(self.running_application, pid)
            if app is not None:
                apps[pid] = app
        return tuple(sorted(apps.values(), key=lambda app: (app.name, app.pid)))

    def list_windows(
        self,
        app: ObservedApp | None,
    ) -> tuple[ObservedWindow, ...]:
        active: set[tuple[int, str]] = set()
        windows: list[ObservedWindow] = []
        for raw in raw_windows(self.quartz):
            pid = int(raw[self.quartz.kCGWindowOwnerPID])
            if app is not None and (
                pid != app.pid
                or process_generation(self.running_application, pid)
                != app.process_generation
            ):
                continue
            window_id = str(int(raw[self.quartz.kCGWindowNumber]))
            key = (pid, window_id)
            active.add(key)
            if key not in self._window_epochs:
                self._window_epochs[key] = 1
            elif key in self._missing_windows:
                self._window_epochs[key] += 1
                self._missing_windows.remove(key)
            bounds = raw.get(self.quartz.kCGWindowBounds, {})
            left = int(bounds.get("X", 0))
            top = int(bounds.get("Y", 0))
            width = int(bounds.get("Width", 0))
            height = int(bounds.get("Height", 0))
            title = str(
                raw.get(self.quartz.kCGWindowName)
                or raw.get(self.quartz.kCGWindowOwnerName)
                or ""
            )
            windows.append(
                ObservedWindow(
                    pid=pid,
                    process_generation=process_generation(
                        self.running_application, pid
                    ),
                    native_window_id=window_id,
                    window_generation=self._window_epochs[key],
                    title=title,
                    bounds=(left, top, left + width, top + height),
                )
            )
        self._missing_windows.update(set(self._window_epochs) - active)
        return tuple(windows)

    def capture(
        self,
        window: ObservedWindow,
        mode: str,
    ) -> BackendCapture:
        if mode in {"ax", "som"} and not self.ax.trusted():
            raise BackendError(
                "permission_required",
                "macOS Accessibility permission is required.",
            )
        if (
            mode in {"vision", "som"}
            and not self.quartz.CGPreflightScreenCaptureAccess()
        ):
            raise BackendError(
                "permission_required",
                "macOS Screen Recording permission is required.",
            )
        current = resolve_window(window, self.list_windows(None))
        elements: tuple[ObservedElement, ...] = ()
        image: bytes | None = None
        media_type: str | None = None
        width: int | None = None
        height: int | None = None
        if mode in {"ax", "som"}:
            elements = self.ax.capture(current)
        if mode in {"vision", "som"}:
            image, width, height = window_png(
                self.quartz,
                self.mutable_data,
                current,
            )
            media_type = "image/png"
        fingerprint = capture_fingerprint(current, elements, image)
        return BackendCapture(
            ui_fingerprint=fingerprint,
            elements=elements,
            image_bytes=image,
            media_type=media_type,
            width=width,
            height=height,
            isolated=True,
        )

    def mutate(self, command: MutationCommand) -> bool:
        if not self.ax.trusted():
            raise BackendError(
                "permission_required",
                "macOS Accessibility permission is required.",
            )
        if command.delivery == "foreground":
            return self._foreground_mutate(command)
        return self.ax.mutate(command)

    def read_element(
        self,
        accessibility_identity: str,
    ) -> ObservedElement | None:
        return self.ax.read(accessibility_identity)

    def focus_state(self) -> FocusSnapshot:
        frontmost = self.workspace.sharedWorkspace().frontmostApplication()
        pid = int(frontmost.processIdentifier()) if frontmost else None
        focused_window_id = None
        if pid is not None:
            focused_window_id = next(
                (
                    str(int(raw[self.quartz.kCGWindowNumber]))
                    for raw in raw_windows(self.quartz)
                    if int(raw[self.quartz.kCGWindowOwnerPID]) == pid
                ),
                None,
            )
        pointer_event = self.quartz.CGEventCreate(None)
        point = self.quartz.CGEventGetLocation(pointer_event)
        return FocusSnapshot(
            frontmost_pid=pid,
            focused_window_id=focused_window_id,
            pointer=(round(point.x), round(point.y)),
            space_id=None,
        )

    def can_restore_focus(self, snapshot: FocusSnapshot) -> bool:
        if snapshot.frontmost_pid is None:
            return False
        return (
            self.running_application.runningApplicationWithProcessIdentifier_(
                snapshot.frontmost_pid
            )
            is not None
        )

    def restore_focus(self, snapshot: FocusSnapshot) -> bool:
        if snapshot.frontmost_pid is None:
            return False
        app = self.running_application.runningApplicationWithProcessIdentifier_(
            snapshot.frontmost_pid
        )
        if app is None:
            return False
        activated = bool(app.activateWithOptions_(self.activate_ignoring_other_apps))
        if snapshot.pointer is not None:
            self.quartz.CGWarpMouseCursorPosition(snapshot.pointer)
        return activated

    def release_inputs(self) -> tuple[str, ...]:
        return macos_foreground.release_inputs(self.quartz)

    def _foreground_mutate(self, command: MutationCommand) -> bool:
        return macos_foreground.mutate(self.quartz, self.ax, command)
