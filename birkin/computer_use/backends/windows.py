"""Native Windows UIA and exact-HWND backend."""

from __future__ import annotations

import hashlib
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
from . import windows_foreground
from .base import BackendError
from .windows_native import capture_hwnd_png


class WindowsBackend:
    backend_id = "windows-uia"
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
        if sys.platform != "win32":
            raise BackendError("backend_unavailable", "Windows is required.")
        try:
            psutil = import_module("psutil")
            win32gui = import_module("win32gui")
            win32process = import_module("win32process")
            win32ui = import_module("win32ui")
            pywinauto = import_module("pywinauto")
            pywinauto_mouse = import_module("pywinauto.mouse")
        except ImportError as exc:
            raise BackendError(
                "backend_unavailable",
                "The Windows desktop optional dependencies are not installed.",
            ) from exc
        self.psutil: Any = psutil
        self.win32gui: Any = win32gui
        self.win32process: Any = win32process
        self.win32ui: Any = win32ui
        self.desktop: Any = pywinauto.Desktop
        self.mouse: Any = pywinauto_mouse
        self._elements: dict[str, Any] = {}

    def probe(self) -> PlatformProbe:
        interactive = bool(self.win32gui.GetDesktopWindow())
        return PlatformProbe(
            platform="win32",
            display_server=DisplayServer.WIN32,
            interactive=interactive,
            accessibility=PermissionState.GRANTED,
            screen_capture=PermissionState.GRANTED,
            responsible_process=sys.executable,
        )

    def list_apps(self) -> tuple[ObservedApp, ...]:
        apps: dict[int, ObservedApp] = {}
        for window in self.list_windows(None):
            try:
                process = self.psutil.Process(window.pid)
                identity = process.exe()
                name = process.name()
            except self.psutil.Error:
                continue
            apps[window.pid] = ObservedApp(
                pid=window.pid,
                process_generation=window.process_generation,
                native_identity=identity,
                name=name,
            )
        return tuple(apps.values())

    def list_windows(
        self,
        app: ObservedApp | None,
    ) -> tuple[ObservedWindow, ...]:
        windows: list[ObservedWindow] = []

        def collect(hwnd: int, _extra: int) -> None:
            if not self.win32gui.IsWindowVisible(hwnd):
                return
            title = self.win32gui.GetWindowText(hwnd).strip()
            if not title:
                return
            _, pid = self.win32process.GetWindowThreadProcessId(hwnd)
            try:
                generation = self._generation(pid)
            except BackendError:
                return
            if app is not None and (
                pid != app.pid or generation != app.process_generation
            ):
                return
            left, top, right, bottom = self.win32gui.GetWindowRect(hwnd)
            bounds = (
                int(left),
                int(top),
                int(right),
                int(bottom),
            )
            windows.append(
                ObservedWindow(
                    pid=pid,
                    process_generation=generation,
                    native_window_id=str(hwnd),
                    window_generation=self._window_generation(hwnd),
                    title=title,
                    bounds=bounds,
                    minimized=bool(self.win32gui.IsIconic(hwnd)),
                )
            )

        self.win32gui.EnumWindows(collect, 0)
        return tuple(windows)

    def capture(
        self,
        window: ObservedWindow,
        mode: str,
    ) -> BackendCapture:
        current = self._resolve(window)
        elements = self._uia_capture(current) if mode in {"ax", "som"} else ()
        image = None
        width = height = None
        if mode in {"vision", "som"}:
            image, width, height = capture_hwnd_png(
                int(current.native_window_id),
                current.bounds,
                win32gui=self.win32gui,
                win32ui=self.win32ui,
            )
        digest = hashlib.sha256(
            (repr(current) + repr(elements)).encode("utf-8") + (image or b"")
        ).hexdigest()
        return BackendCapture(
            ui_fingerprint=digest,
            elements=elements,
            image_bytes=image,
            media_type="image/png" if image is not None else None,
            width=width,
            height=height,
            isolated=True,
        )

    def mutate(self, command: MutationCommand) -> bool:
        wrapper = self._elements.get(command.accessibility_identity)
        if wrapper is None:
            raise BackendError("stale_ref", "The UIA element changed.")
        if command.delivery == "foreground":
            return self._foreground_mutate(wrapper, command)
        set_edit_text = getattr(type(wrapper), "set_edit_text", None)
        if command.action == "type" and callable(set_edit_text):
            text = str(command.value or "")
            if command.mode == "append":
                text = f"{self._wrapper_value(wrapper)}{text}"
            elif command.mode == "insert":
                raise BackendError(
                    "background_delivery_unsupported",
                    "UIA cannot prove the current insertion point.",
                )
            set_edit_text(wrapper, text)
            return True
        invoke = getattr(type(wrapper), "invoke", None)
        if command.action == "click" and callable(invoke):
            invoke(wrapper)
            return True
        raise BackendError(
            "background_delivery_unsupported",
            "The UIA pattern does not support this semantic action.",
        )

    def read_element(
        self,
        accessibility_identity: str,
    ) -> ObservedElement | None:
        wrapper = self._elements.get(accessibility_identity)
        if wrapper is None:
            return None
        try:
            return self._observed(wrapper)
        except (AttributeError, OSError, RuntimeError, ValueError):
            return None

    def focus_state(self) -> FocusSnapshot:
        hwnd = int(self.win32gui.GetForegroundWindow())
        _, pid = self.win32process.GetWindowThreadProcessId(hwnd)
        point = self.win32gui.GetCursorPos()
        return FocusSnapshot(pid or None, str(hwnd) if hwnd else None, point, None)

    def can_restore_focus(self, snapshot: FocusSnapshot) -> bool:
        return bool(snapshot.focused_window_id)

    def restore_focus(self, snapshot: FocusSnapshot) -> bool:
        if snapshot.focused_window_id is None:
            return False
        try:
            self.win32gui.SetForegroundWindow(int(snapshot.focused_window_id))
            if snapshot.pointer is not None:
                self.mouse.move(coords=snapshot.pointer)
            return True
        except (AttributeError, OSError, RuntimeError, ValueError):
            return False

    def release_inputs(self) -> tuple[str, ...]:
        return windows_foreground.release_inputs(self.mouse)

    def _foreground_mutate(
        self,
        wrapper: Any,
        command: MutationCommand,
    ) -> bool:
        return windows_foreground.mutate(
            self.mouse,
            self.win32gui,
            self._elements,
            wrapper,
            command,
        )

    def _uia_capture(self, window: ObservedWindow) -> tuple[ObservedElement, ...]:
        root = (
            self.desktop(backend="uia")
            .window(handle=int(window.native_window_id))
            .wrapper_object()
        )
        wrappers = [root, *root.descendants()[:499]]
        observed = tuple(self._observed(wrapper) for wrapper in wrappers)
        for item, wrapper in zip(observed, wrappers):
            self._elements[item.accessibility_identity] = wrapper
        return observed

    def _observed(self, wrapper: Any) -> ObservedElement:
        info = wrapper.element_info
        raw = repr((info.process_id, info.runtime_id, info.automation_id))
        identity = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        actions: set[str] = set()
        if bool(getattr(info.element, "CurrentIsInvokePatternAvailable", False)):
            actions.add("press")
        if callable(getattr(type(wrapper), "set_edit_text", None)):
            actions.add("set_value")
        is_password = bool(
            getattr(info, "is_password", False)
            or getattr(getattr(info, "element", None), "CurrentIsPassword", False)
        )
        value = (
            None
            if is_password
            else (
                self._wrapper_value(wrapper)
                if "set_value" in actions
                else wrapper.window_text()
            )
        )
        sensitive = "password" if is_password else None
        return ObservedElement(
            accessibility_identity=identity,
            accessibility_path=(str(info.runtime_id),),
            role=str(info.control_type),
            name=str(info.name or ""),
            value=value,
            supported_actions=frozenset(actions),
            sensitive_category=sensitive,
        )

    @staticmethod
    def _wrapper_value(wrapper: Any) -> str:
        return str(wrapper.iface_value.CurrentValue)

    def _generation(self, pid: int) -> str:
        try:
            created = int(self.psutil.Process(pid).create_time() * 1_000_000)
        except self.psutil.Error as exc:
            raise BackendError(
                "identity_incomplete", "PID generation missing."
            ) from exc
        return f"{pid}:{created}"

    def _resolve(self, expected: ObservedWindow) -> ObservedWindow:
        matches = [
            window
            for window in self.list_windows(None)
            if window.pid == expected.pid
            and window.process_generation == expected.process_generation
            and window.native_window_id == expected.native_window_id
            and window.window_generation == expected.window_generation
        ]
        if len(matches) != 1:
            raise BackendError("stale_ref", "The HWND changed.")
        return matches[0]

    def _window_generation(self, hwnd: int) -> int:
        root = self.desktop(backend="uia").window(handle=hwnd)
        runtime_id = tuple(root.element_info.runtime_id or ())
        if not runtime_id:
            raise BackendError(
                "identity_incomplete",
                "The UIA window runtime identity is unavailable.",
            )
        digest = hashlib.sha256(repr(runtime_id).encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big")
