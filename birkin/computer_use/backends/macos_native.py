"""Small in-process macOS identity and exact-window capture helpers."""

from __future__ import annotations

import hashlib
from typing import Any

from ..models import ObservedApp, ObservedElement, ObservedWindow
from .base import BackendError


def raw_windows(quartz: Any) -> list[dict[str, Any]]:
    options = (
        quartz.kCGWindowListOptionOnScreenOnly
        | quartz.kCGWindowListExcludeDesktopElements
    )
    windows = quartz.CGWindowListCopyWindowInfo(
        options,
        quartz.kCGNullWindowID,
    )
    return [
        raw
        for raw in windows
        if int(raw.get(quartz.kCGWindowLayer, 0)) == 0
        and int(raw.get(quartz.kCGWindowNumber, 0)) > 0
        and int(raw.get(quartz.kCGWindowOwnerPID, 0)) > 0
    ]


def process_generation(running_application: Any, pid: int) -> str:
    raw = running_application.runningApplicationWithProcessIdentifier_(pid)
    if raw is None:
        raise BackendError(
            "identity_incomplete",
            f"Process generation is unavailable for PID {pid}.",
        )
    launched = raw.launchDate()
    if launched is not None:
        micros = int(launched.timeIntervalSince1970() * 1_000_000)
        return f"{pid}:{micros}"
    try:
        import psutil
    except ImportError as exc:
        raise BackendError(
            "identity_incomplete",
            f"Process generation is unavailable for PID {pid}.",
        ) from exc
    try:
        micros = int(psutil.Process(pid).create_time() * 1_000_000)
    except psutil.Error as exc:
        raise BackendError(
            "identity_incomplete",
            f"Process generation is unavailable for PID {pid}.",
        ) from exc
    return f"{pid}:{micros}"


def observed_app(running_application: Any, pid: int) -> ObservedApp | None:
    raw = running_application.runningApplicationWithProcessIdentifier_(pid)
    if raw is None:
        return None
    identity = str(raw.bundleIdentifier() or f"pid:{pid}")
    return ObservedApp(
        pid=pid,
        process_generation=process_generation(running_application, pid),
        native_identity=identity,
        name=str(raw.localizedName() or identity),
    )


def window_png(
    quartz: Any,
    mutable_data: Any,
    window: ObservedWindow,
) -> tuple[bytes, int, int]:
    if not quartz.CGPreflightScreenCaptureAccess():
        raise BackendError(
            "permission_required",
            "macOS Screen Recording permission is required.",
        )
    image = quartz.CGWindowListCreateImage(
        quartz.CGRectNull,
        quartz.kCGWindowListOptionIncludingWindow,
        int(window.native_window_id),
        quartz.kCGWindowImageBoundsIgnoreFraming,
    )
    if image is None:
        raise BackendError("target_gone", "Window capture failed.")
    data = mutable_data.data()
    destination = quartz.CGImageDestinationCreateWithData(
        data,
        "public.png",
        1,
        None,
    )
    quartz.CGImageDestinationAddImage(destination, image, None)
    if not quartz.CGImageDestinationFinalize(destination):
        raise BackendError("verification_unsupported", "PNG encoding failed.")
    return (
        bytes(data),
        int(quartz.CGImageGetWidth(image)),
        int(quartz.CGImageGetHeight(image)),
    )


def capture_fingerprint(
    window: ObservedWindow,
    elements: tuple[ObservedElement, ...],
    image: bytes | None,
) -> str:
    digest = hashlib.sha256()
    digest.update(repr(window).encode("utf-8"))
    digest.update(repr(elements).encode("utf-8"))
    if image is not None:
        digest.update(hashlib.sha256(image).digest())
    return digest.hexdigest()


def resolve_window(
    expected: ObservedWindow,
    current: tuple[ObservedWindow, ...],
) -> ObservedWindow:
    matches = [
        window
        for window in current
        if window.pid == expected.pid
        and window.process_generation == expected.process_generation
        and window.native_window_id == expected.native_window_id
        and window.window_generation == expected.window_generation
    ]
    if len(matches) != 1:
        raise BackendError("stale_ref", "The macOS window changed.")
    return matches[0]


def ax_pair(api: Any, value: Any, value_type: int) -> tuple[float, float] | None:
    if value is None:
        return None
    success, result = api.AXValueGetValue(value, value_type, None)
    if not success:
        return None
    first = getattr(result, "x", getattr(result, "width", None))
    second = getattr(result, "y", getattr(result, "height", None))
    if first is None or second is None:
        return None
    return float(first), float(second)


def ax_identity(
    window: ObservedWindow,
    indexes: tuple[int, ...],
    role: str,
    identifier: str,
) -> str:
    raw = "|".join(
        (
            str(window.pid),
            window.process_generation,
            window.native_window_id,
            "/".join(map(str, indexes)),
            role,
            identifier,
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
