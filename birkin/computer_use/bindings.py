"""Session-local opaque reference issuance and exact binding checks."""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass

from .binding_models import (
    AppBinding,
    ElementBinding,
    SnapshotBinding,
    WindowBinding,
)
from .models import CaptureMode, ElementTarget, SnapshotReference


@dataclass(frozen=True, slots=True)
class BindingError(RuntimeError):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


class BindingStore:
    """Own all refs for one backend session."""

    def __init__(self, *, session_id: str, backend_id: str):
        self.session_id = session_id
        self.backend_id = backend_id
        self._apps: dict[str, AppBinding] = {}
        self._windows: dict[str, WindowBinding] = {}
        self._snapshots: dict[str, SnapshotBinding] = {}
        self._elements: dict[str, ElementBinding] = {}
        self._window_generation: dict[str, int] = {}
        self._observed_processes: dict[int, str] = {}

    @staticmethod
    def _token(kind: str) -> str:
        return f"cu_{kind}_{secrets.token_urlsafe(24)}"

    def bind_app(
        self,
        *,
        pid: int,
        process_generation: str,
        native_identity: str,
    ) -> str:
        token = self._token("app")
        self._apps[token] = AppBinding(
            self.session_id,
            self.backend_id,
            pid,
            process_generation,
            native_identity,
        )
        self._observed_processes[pid] = process_generation
        return token

    def bind_window(
        self,
        *,
        app_ref: str,
        native_window_id: str,
        window_generation: int,
    ) -> str:
        app = self._app(app_ref)
        token = self._token("window")
        self._windows[token] = WindowBinding(
            self.session_id,
            self.backend_id,
            app_ref,
            app.pid,
            app.process_generation,
            native_window_id,
            window_generation,
        )
        self._window_generation[token] = 0
        return token

    def begin_snapshot(
        self,
        *,
        app_ref: str,
        window_ref: str,
        mode: CaptureMode,
        ui_fingerprint: str,
    ) -> SnapshotReference:
        app = self._app(app_ref)
        window = self._window(window_ref)
        if window.app_ref != app_ref or window.pid != app.pid:
            raise BindingError(
                "identity_mismatch",
                "The app and window references do not identify one target.",
            )
        generation = self._window_generation[window_ref] + 1
        self._window_generation[window_ref] = generation
        token = self._token("snapshot")
        self._snapshots[token] = SnapshotBinding(
            self.session_id,
            self.backend_id,
            app_ref,
            window_ref,
            app.process_generation,
            window.native_window_id,
            window.window_generation,
            generation,
            mode,
            ui_fingerprint,
        )
        return SnapshotReference(token, generation, mode)

    def bind_element(
        self,
        *,
        snapshot_ref: str,
        accessibility_identity: str,
        accessibility_path: tuple[str, ...],
    ) -> str:
        snapshot = self._snapshot(snapshot_ref)
        path_digest = hashlib.sha256(
            json.dumps(
                accessibility_path,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        token = self._token("element")
        self._elements[token] = ElementBinding(
            self.session_id,
            self.backend_id,
            snapshot.app_ref,
            snapshot.window_ref,
            snapshot_ref,
            snapshot.process_generation,
            snapshot.native_window_id,
            snapshot.window_generation,
            snapshot.snapshot_generation,
            accessibility_identity,
            path_digest,
        )
        return token

    def observe_process_generation(
        self,
        *,
        pid: int,
        process_generation: str,
    ) -> None:
        self._observed_processes[pid] = process_generation

    def invalidate_window(self, window_ref: str) -> int:
        """Advance a window epoch after mutation or observed state change."""
        self._window(window_ref)
        generation = self._window_generation[window_ref] + 1
        self._window_generation[window_ref] = generation
        return generation

    def element_binding(self, element_ref: str) -> ElementBinding:
        try:
            return self._elements[element_ref]
        except KeyError as exc:
            raise self._foreign_ref() from exc

    def resolve_element(self, target: ElementTarget) -> ElementBinding:
        app = self._app(target.app_ref)
        window = self._window(target.window_ref)
        snapshot = self._snapshot(target.snapshot_ref)
        element = self.element_binding(target.element_ref)
        if (
            window.app_ref != target.app_ref
            or snapshot.app_ref != target.app_ref
            or snapshot.window_ref != target.window_ref
            or element.app_ref != target.app_ref
            or element.window_ref != target.window_ref
            or element.snapshot_ref != target.snapshot_ref
        ):
            raise BindingError(
                "identity_mismatch",
                "The supplied references do not bind one captured element.",
            )
        current_process = self._observed_processes.get(app.pid)
        current_snapshot = self._window_generation.get(target.window_ref)
        if (
            current_process != app.process_generation
            or current_snapshot != snapshot.snapshot_generation
            or element.snapshot_generation != snapshot.snapshot_generation
            or window.process_generation != app.process_generation
        ):
            raise BindingError(
                "stale_ref",
                "The captured element is stale; capture the target again.",
            )
        return element

    def _app(self, token: str) -> AppBinding:
        try:
            return self._apps[token]
        except KeyError as exc:
            raise self._foreign_ref() from exc

    def _window(self, token: str) -> WindowBinding:
        try:
            return self._windows[token]
        except KeyError as exc:
            raise self._foreign_ref() from exc

    def _snapshot(self, token: str) -> SnapshotBinding:
        try:
            return self._snapshots[token]
        except KeyError as exc:
            raise self._foreign_ref() from exc

    @staticmethod
    def _foreign_ref() -> BindingError:
        return BindingError(
            "cross_session_ref",
            "The reference was not issued by this Computer Use session.",
        )
