"""Explicit runtime construction without installation or permission prompts."""

from __future__ import annotations

import os
import secrets
import sys
from collections.abc import Callable
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from .approval_bridge import ApprovalBridge
from .artifacts import ArtifactStore
from .backends import select_backend
from .backends.base import BackendError, ComputerUseBackend
from .capability_types import DisplayServer, PermissionState, PlatformProbe
from .events import ComputerEvent
from .models import (
    BackendCapture,
    FocusSnapshot,
    MutationCommand,
    ObservedApp,
    ObservedElement,
    ObservedWindow,
)
from .service import ComputerUseService
from .session_policy import SessionCapability


class UnavailableBackend:
    backend_id = "unavailable"
    foreground_actions: frozenset[str] = frozenset()

    def probe(self) -> PlatformProbe:
        display = DisplayServer.UNKNOWN
        if sys.platform == "darwin":
            display = DisplayServer.QUARTZ
        elif sys.platform == "win32":
            display = DisplayServer.WIN32
        elif sys.platform.startswith("linux"):
            display = (
                DisplayServer.WAYLAND
                if os.environ.get("WAYLAND_DISPLAY")
                else DisplayServer.X11
                if os.environ.get("DISPLAY")
                else DisplayServer.UNKNOWN
            )
        return PlatformProbe(
            platform=sys.platform,
            display_server=display,
            interactive=display is not DisplayServer.UNKNOWN,
            accessibility=PermissionState.UNKNOWN,
            screen_capture=PermissionState.UNKNOWN,
            responsible_process=sys.executable,
        )

    def list_apps(self) -> tuple[ObservedApp, ...]:
        return ()

    def list_windows(
        self,
        app: ObservedApp | None,
    ) -> tuple[ObservedWindow, ...]:
        del app
        return ()

    def capture(
        self,
        window: ObservedWindow,
        mode: str,
    ) -> BackendCapture:
        del window, mode
        raise BackendError(
            "backend_unavailable",
            "No supported native Computer Use backend is available.",
        )

    def mutate(self, command: MutationCommand) -> bool:
        del command
        raise BackendError(
            "backend_unavailable",
            "No supported native Computer Use backend is available.",
        )

    def read_element(
        self,
        accessibility_identity: str,
    ) -> ObservedElement | None:
        del accessibility_identity
        return None

    def focus_state(self) -> FocusSnapshot:
        return FocusSnapshot(None, None, None, None)

    def can_restore_focus(self, snapshot: FocusSnapshot) -> bool:
        del snapshot
        return False

    def restore_focus(self, snapshot: FocusSnapshot) -> bool:
        del snapshot
        return False

    def release_inputs(self) -> tuple[str, ...]:
        return ()


def default_backend() -> ComputerUseBackend:
    """Select an already installed native backend without side effects."""
    display_server = (
        DisplayServer.QUARTZ
        if sys.platform == "darwin"
        else DisplayServer.WIN32
        if sys.platform == "win32"
        else DisplayServer.WAYLAND
        if (
            sys.platform.startswith("linux")
            and os.environ.get("WAYLAND_DISPLAY")
            and not os.environ.get("DISPLAY")
        )
        else DisplayServer.XWAYLAND
        if (
            sys.platform.startswith("linux")
            and os.environ.get("WAYLAND_DISPLAY")
            and os.environ.get("DISPLAY")
        )
        else DisplayServer.X11
        if sys.platform.startswith("linux") and os.environ.get("DISPLAY")
        else DisplayServer.UNKNOWN
    )
    candidates = {
        "AppKit",
        "ApplicationServices",
        "Foundation",
        "Quartz",
        "Xlib",
        "pyatspi",
        "pywinauto",
        "win32gui",
        "win32process",
        "win32ui",
    }
    available = frozenset(name for name in candidates if find_spec(name) is not None)
    selection = select_backend(
        platform="linux" if sys.platform.startswith("linux") else sys.platform,
        display_server=display_server,
        available_modules=available,
    )
    if not selection.available:
        return UnavailableBackend()
    try:
        if selection.backend_id == "macos-ax-quartz":
            from .backends.macos import MacOSBackend

            return MacOSBackend()
        if selection.backend_id == "windows-uia":
            from .backends.windows import WindowsBackend

            return WindowsBackend()
        if selection.backend_id == "linux-atspi-x11":
            from .backends.linux import LinuxBackend

            return LinuxBackend()
    except (BackendError, ImportError):
        return UnavailableBackend()
    return UnavailableBackend()


def create_service(
    *,
    artifact_root: Path,
    session_id: str | None = None,
    emit: Callable[[ComputerEvent], None] | None = None,
    policy_config: dict[str, Any] | None = None,
) -> ComputerUseService:
    resolved_session_id = session_id or "cu_session_" + secrets.token_urlsafe(24)
    return ComputerUseService(
        backend=default_backend(),
        artifact_store=ArtifactStore(artifact_root),
        session_id=resolved_session_id,
        approval_bridge=ApprovalBridge(session_id=resolved_session_id),
        emit=emit,
        session_capability=_session_capability(
            resolved_session_id,
            policy_config or {},
        ),
    )


def _session_capability(
    session_id: str,
    policy: dict[str, Any],
) -> SessionCapability:
    default_operations = {
        "click",
        "double_click",
        "right_click",
        "middle_click",
        "drag",
        "scroll",
        "type",
        "key",
    }

    def strings(name: str) -> frozenset[str]:
        value = policy.get(name)
        if not isinstance(value, list):
            return frozenset()
        return frozenset(item for item in value if isinstance(item, str))

    def optional_strings(name: str) -> frozenset[str] | None:
        value = policy.get(name)
        if value is None:
            return None
        if not isinstance(value, list):
            return frozenset()
        return frozenset(item for item in value if isinstance(item, str))

    allowed_apps = strings("allowed_apps")
    allowed_windows = optional_strings("allowed_windows")
    operations = strings("allowed_operations") or frozenset(default_operations)
    raw_max_actions = policy.get("max_actions", 200)
    max_actions = (
        max(1, min(10_000, raw_max_actions))
        if isinstance(raw_max_actions, int) and not isinstance(raw_max_actions, bool)
        else 200
    )
    return SessionCapability(
        session_id=session_id,
        actor="agent",
        source="tool",
        allowed_operations=operations,
        allowed_apps=allowed_apps,
        denied_apps=strings("denied_apps"),
        allowed_windows=allowed_windows,
        denied_windows=strings("denied_windows"),
        max_actions=max_actions,
    )
