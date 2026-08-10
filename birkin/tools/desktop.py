"""Opt-in observation of visible Windows desktop windows."""

from __future__ import annotations

import io
import json
from dataclasses import asdict, dataclass
from typing import Any

from . import Tool, ToolContext, ToolResult
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
    try:
        import win32gui
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
        from PIL import ImageGrab
    except ImportError:
        return ToolResult(
            "Window screenshots require Pillow on Windows.", is_error=True
        )
    try:
        image = ImageGrab.grab(
            bbox=(window.left, window.top, window.right, window.bottom),
            all_screens=True,
        )
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=True)
    except OSError as exc:
        return ToolResult(f"Window screenshot failed: {exc}", is_error=True)
    data = output.getvalue()
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
                "Capture one visible Windows desktop window and attach it for "
                "visual inspection. Match by handle or title substring."
            ),
            input_schema=target_schema,
            fn=_window_screenshot,
        ),
    ]
