"""Opt-in observation of visible desktop windows."""

from __future__ import annotations

import io
import importlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from dataclasses import asdict, dataclass
from typing import Any

from ._types import Tool, ToolContext, ToolResult
from .vision import MAX_IMAGE_BYTES, _image_content


@dataclass(frozen=True, slots=True)
class DesktopWindow:
    handle: int
    title: str
    left: int
    top: int
    right: int
    bottom: int
    minimized: bool

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


@dataclass(frozen=True, slots=True)
class DesktopUnavailableError(RuntimeError):
    reason: str

    def __str__(self) -> str:
        return self.reason


def _visible_windows() -> list[DesktopWindow]:
    if sys.platform == "win32":
        return _windows_visible_windows()
    if sys.platform == "darwin":
        return _macos_visible_windows()
    if sys.platform.startswith("linux"):
        return _linux_visible_windows()
    raise DesktopUnavailableError(
        reason=f"Desktop observation is unavailable on {sys.platform}."
    )


def _windows_visible_windows() -> list[DesktopWindow]:
    try:
        win32gui = importlib.import_module("win32gui")
    except ImportError as exc:
        raise DesktopUnavailableError(
            reason="Desktop observation requires pywin32 on Windows."
        ) from exc

    windows: list[DesktopWindow] = []

    def collect(handle: int, _extra: int) -> None:
        if not win32gui.IsWindowVisible(handle):
            return
        title = win32gui.GetWindowText(handle).strip()
        if not title:
            return
        left, top, right, bottom = win32gui.GetWindowRect(handle)
        if right <= left or bottom <= top:
            return
        windows.append(
            DesktopWindow(
                handle=handle,
                title=title,
                left=left,
                top=top,
                right=right,
                bottom=bottom,
                minimized=bool(win32gui.IsIconic(handle)),
            )
        )

    win32gui.EnumWindows(collect, 0)
    return windows


def _macos_visible_windows() -> list[DesktopWindow]:
    try:
        Quartz = importlib.import_module("Quartz")
    except ImportError as exc:
        raise DesktopUnavailableError(
            reason="Desktop observation requires Quartz on macOS."
        ) from exc

    options = (
        Quartz.kCGWindowListOptionOnScreenOnly
        | Quartz.kCGWindowListExcludeDesktopElements
    )
    raw_windows = Quartz.CGWindowListCopyWindowInfo(
        options,
        Quartz.kCGNullWindowID,
    )
    windows: list[DesktopWindow] = []
    for raw in raw_windows:
        if int(raw.get(Quartz.kCGWindowLayer, 0)) != 0:
            continue
        bounds = raw.get(Quartz.kCGWindowBounds, {})
        left = int(bounds.get("X", 0))
        top = int(bounds.get("Y", 0))
        width = int(bounds.get("Width", 0))
        height = int(bounds.get("Height", 0))
        title = str(
            raw.get(Quartz.kCGWindowName)
            or raw.get(Quartz.kCGWindowOwnerName)
            or ""
        ).strip()
        if not title or width <= 0 or height <= 0:
            continue
        windows.append(
            DesktopWindow(
                handle=int(raw[Quartz.kCGWindowNumber]),
                title=title,
                left=left,
                top=top,
                right=left + width,
                bottom=top + height,
                minimized=False,
            )
        )
    return windows


def _linux_visible_windows() -> list[DesktopWindow]:
    try:
        pywinctl = importlib.import_module("pywinctl")
    except ImportError as exc:
        raise DesktopUnavailableError(
            reason="Desktop observation requires PyWinCtl on Linux."
        ) from exc

    windows: list[DesktopWindow] = []
    for raw in pywinctl.getAllWindows():
        title = str(raw.title).strip()
        left = int(raw.left)
        top = int(raw.top)
        right = int(raw.right)
        bottom = int(raw.bottom)
        if not title or right <= left or bottom <= top:
            continue
        windows.append(
            DesktopWindow(
                handle=int(raw.getHandle()),
                title=title,
                left=left,
                top=top,
                right=right,
                bottom=bottom,
                minimized=bool(raw.isMinimized),
            )
        )
    return windows


def _window_match(inp: dict[str, Any]) -> DesktopWindow | None:
    raw_handle = inp.get("handle")
    title = str(inp.get("title", "")).casefold().strip()
    try:
        handle = int(raw_handle) if raw_handle is not None else None
    except (TypeError, ValueError):
        return None
    return next(
        (
            window
            for window in _visible_windows()
            if (handle is not None and window.handle == handle)
            or (title and title in window.title.casefold())
        ),
        None,
    )


def _desktop_windows(inp: dict[str, Any], _ctx: ToolContext) -> ToolResult:
    title = str(inp.get("title", "")).casefold().strip()
    windows = [
        {
            **asdict(window),
            "width": window.width,
            "height": window.height,
        }
        for window in _visible_windows()
        if not title or title in window.title.casefold()
    ]
    return ToolResult(json.dumps(windows, ensure_ascii=False, indent=2))


def _window_screenshot(inp: dict[str, Any], _ctx: ToolContext) -> ToolResult:
    window = _window_match(inp)
    if window is None:
        return ToolResult(
            "No visible window matched the supplied title or handle.",
            is_error=True,
        )
    if window.minimized:
        return ToolResult(
            f"Window {window.handle} is minimized; restore it before capture.",
            is_error=True,
        )
    try:
        data = (
            _macos_window_png(window)
            if sys.platform == "darwin"
            else _bounding_box_png(window)
        )
    except (DesktopUnavailableError, OSError) as exc:
        return ToolResult(f"Window screenshot failed: {exc}", is_error=True)
    if len(data) > MAX_IMAGE_BYTES:
        return ToolResult(
            "Window screenshot exceeds the 5 MB limit.", is_error=True
        )
    return ToolResult(
        _image_content(
            data,
            str(inp.get("question", "")),
            f"window {window.handle} ({window.title})",
        )
    )


def _bounding_box_png(window: DesktopWindow) -> bytes:
    try:
        from PIL import ImageGrab
    except ImportError as exc:
        raise DesktopUnavailableError(
            reason="Window screenshots require Pillow."
        ) from exc
    image = ImageGrab.grab(
        bbox=(window.left, window.top, window.right, window.bottom),
        all_screens=True,
    )
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _macos_window_png(window: DesktopWindow) -> bytes:
    Quartz = importlib.import_module("Quartz")
    if not Quartz.CGPreflightScreenCaptureAccess():
        raise DesktopUnavailableError(
            reason=(
                "macOS Screen Recording permission is required for window "
                "screenshots."
            )
        )
    with tempfile.TemporaryDirectory(prefix="birkin-window-") as temp_dir:
        target = Path(temp_dir) / "window.png"
        proc = subprocess.run(
            [
                "/usr/sbin/screencapture",
                "-x",
                "-l",
                str(window.handle),
                target,
            ],
            capture_output=True,
            text=True,
            errors="replace",
        )
        if proc.returncode != 0 or not target.is_file():
            detail = (proc.stderr or proc.stdout).strip()
            raise OSError(detail or "native window capture failed")
        return target.read_bytes()


def tools() -> list[Tool]:
    target_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "handle": {"type": "integer"},
            "question": {"type": "string"},
        },
    }
    return [
        Tool(
            name="desktop_windows",
            description="List visible desktop windows and their current state.",
            input_schema={
                "type": "object",
                "properties": {"title": {"type": "string"}},
            },
            fn=_desktop_windows,
        ),
        Tool(
            name="window_screenshot",
            description=(
                "Capture one visible desktop window and attach it for "
                "visual inspection. Match by handle or title substring."
            ),
            input_schema=target_schema,
            fn=_window_screenshot,
        ),
    ]
