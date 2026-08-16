"""X11 process identity, metadata, and exact-window capture helpers."""

from __future__ import annotations

import io
from importlib import import_module
from typing import Any

from .base import BackendError


def process_generation(pid: int) -> str:
    import psutil

    try:
        created = int(psutil.Process(pid).create_time() * 1_000_000)
    except psutil.Error as exc:
        raise BackendError("identity_incomplete", "PID generation missing.") from exc
    return f"{pid}:{created}"


def property_int(display: Any, window: Any, name: str) -> int | None:
    xlib = import_module("Xlib.X")

    value = window.get_full_property(
        display.intern_atom(name),
        xlib.AnyPropertyType,
    )
    return int(value.value[0]) if value is not None and len(value.value) else None


def window_title(display: Any, window: Any) -> str:
    xlib = import_module("Xlib.X")

    atom = display.intern_atom("_NET_WM_NAME")
    value = window.get_full_property(atom, xlib.AnyPropertyType)
    if value is None:
        return str(window.get_wm_name() or "")
    return bytes(value.value).decode("utf-8", errors="replace")


def exact_window_png(
    display: Any,
    native_window_id: str,
) -> tuple[bytes, int, int]:
    image_module = import_module("PIL.Image")
    xlib = import_module("Xlib.X")

    resource = display.create_resource_object(
        "window",
        int(native_window_id),
    )
    geometry = resource.get_geometry()
    raw = resource.get_image(
        0,
        0,
        geometry.width,
        geometry.height,
        xlib.ZPixmap,
        0xFFFFFFFF,
    )
    if raw is None:
        raise BackendError("target_gone", "X11 window capture failed.")
    image = image_module.frombytes(
        "RGB",
        (geometry.width, geometry.height),
        raw.data,
        "raw",
        "BGRX",
    )
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue(), geometry.width, geometry.height
