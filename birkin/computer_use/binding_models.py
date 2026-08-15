"""Internal immutable binding records."""

from __future__ import annotations

from dataclasses import dataclass

from .models import CaptureMode


@dataclass(frozen=True, slots=True)
class AppBinding:
    session_id: str
    backend_id: str
    pid: int
    process_generation: str
    native_identity: str


@dataclass(frozen=True, slots=True)
class WindowBinding:
    session_id: str
    backend_id: str
    app_ref: str
    pid: int
    process_generation: str
    native_window_id: str
    window_generation: int


@dataclass(frozen=True, slots=True)
class SnapshotBinding:
    session_id: str
    backend_id: str
    app_ref: str
    window_ref: str
    process_generation: str
    native_window_id: str
    window_generation: int
    snapshot_generation: int
    mode: CaptureMode
    ui_fingerprint: str


@dataclass(frozen=True, slots=True)
class ElementBinding:
    session_id: str
    backend_id: str
    app_ref: str
    window_ref: str
    snapshot_ref: str
    process_generation: str
    native_window_id: str
    window_generation: int
    snapshot_generation: int
    accessibility_identity: str
    accessibility_path_digest: str
