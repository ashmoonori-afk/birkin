"""Exact HWND capture helpers."""

from __future__ import annotations

import io
from importlib import import_module
from typing import Any

from .base import BackendError


def capture_hwnd_png(
    hwnd: int,
    bounds: tuple[int, int, int, int],
    *,
    win32gui: Any,
    win32ui: Any,
) -> tuple[bytes, int, int]:
    image_module = import_module("PIL.Image")

    left, top, right, bottom = bounds
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        raise BackendError("target_gone", "The HWND has no drawable bounds.")
    window_dc = win32gui.GetWindowDC(hwnd)
    source_dc = win32ui.CreateDCFromHandle(window_dc)
    memory_dc = source_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(source_dc, width, height)
    memory_dc.SelectObject(bitmap)
    try:
        windll: Any = import_module("ctypes").windll
        printed = windll.user32.PrintWindow(
            hwnd,
            memory_dc.GetSafeHdc(),
            2,
        )
        if not printed:
            raise BackendError(
                "capture_isolation_unavailable",
                "PrintWindow could not isolate the exact HWND.",
            )
        raw = bytes(bitmap.GetBitmapBits(True))
        expected_size = width * height * 4
        if len(raw) < expected_size:
            raise BackendError(
                "capture_isolation_unavailable",
                "PrintWindow returned an incomplete bitmap.",
            )
        image = image_module.frombuffer(
            "RGB",
            (width, height),
            raw[:expected_size],
            "raw",
            "BGRX",
            0,
            -1,
        )
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=True)
        return output.getvalue(), width, height
    finally:
        win32gui.DeleteObject(bitmap.GetHandle())
        memory_dc.DeleteDC()
        source_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, window_dc)
