"""App/window discovery and scoped capture service component."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, cast

from .artifacts import ArtifactScope
from .models import BackendCapture, CaptureMode, ObservedElement, ObservedWindow
from .redaction import redact_text
from .service_types import ServiceState


class DiscoveryMixin:
    def _list_apps(self: ServiceState) -> dict[str, Any]:
        apps: list[dict[str, Any]] = []
        for app in self.backend.list_apps():
            if not self.session_capability.app_allowed(app.native_identity):
                continue
            key = (app.pid, app.process_generation, app.native_identity)
            app_ref = self._app_refs.get(key)
            if app_ref is None:
                app_ref = self.bindings.bind_app(
                    pid=app.pid,
                    process_generation=app.process_generation,
                    native_identity=app.native_identity,
                )
                self._app_refs[key] = app_ref
            self._apps[app_ref] = app
            apps.append(
                {
                    "app_ref": app_ref,
                    "pid": app.pid,
                    "native_identity": app.native_identity,
                    "name": redact_text(app.name, max_chars=256),
                }
            )
        return {"ok": True, "session_id": self.session_id, "apps": apps}

    def _list_windows(
        self: ServiceState,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        app_ref = request.get("app_ref")
        app = self._apps.get(str(app_ref)) if app_ref else None
        if app_ref and app is None:
            return self._refused("cross_session_ref")
        windows: list[dict[str, Any]] = []
        for window in self.backend.list_windows(app):
            if not self.session_capability.window_allowed(window.native_window_id):
                continue
            bound_app_ref = str(app_ref) if app_ref else self._app_ref(window)
            if bound_app_ref is None:
                return self._refused("identity_incomplete")
            key = (
                window.pid,
                window.process_generation,
                window.native_window_id,
                window.window_generation,
            )
            window_ref = self._window_refs.get(key)
            if window_ref is None:
                window_ref = self.bindings.bind_window(
                    app_ref=bound_app_ref,
                    native_window_id=window.native_window_id,
                    window_generation=window.window_generation,
                )
                self._window_refs[key] = window_ref
            self._windows[window_ref] = window
            self._window_apps[window_ref] = bound_app_ref
            windows.append(
                {
                    "window_ref": window_ref,
                    "app_ref": bound_app_ref,
                    "native_window_id": window.native_window_id,
                    "title": redact_text(window.title, max_chars=256),
                    "bounds": list(window.bounds),
                    "minimized": window.minimized,
                }
            )
        return {
            "ok": True,
            "session_id": self.session_id,
            "windows": windows,
        }

    def _app_ref(
        self: ServiceState,
        window: ObservedWindow,
    ) -> str | None:
        matches = [
            ref
            for ref, app in self._apps.items()
            if app.pid == window.pid
            and app.process_generation == window.process_generation
        ]
        return matches[0] if len(matches) == 1 else None

    def _capture(
        self: ServiceState,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        target = request.get("target")
        if not isinstance(target, dict):
            return self._refused("identity_incomplete")
        resolved = self._capture_target(target)
        if isinstance(resolved, dict):
            return resolved
        app_ref, window_ref, window = resolved
        raw_mode = str(request.get("mode", ""))
        if raw_mode not in {"ax", "vision", "som"}:
            return self._refused("unsupported")
        mode = cast(CaptureMode, raw_mode)
        capture = self.backend.capture(window, mode)
        snapshot = self.bindings.begin_snapshot(
            app_ref=app_ref,
            window_ref=window_ref,
            mode=mode,
            ui_fingerprint=capture.ui_fingerprint,
        )
        elements = []
        for element in capture.elements:
            element_ref = self.bindings.bind_element(
                snapshot_ref=snapshot.token,
                accessibility_identity=element.accessibility_identity,
                accessibility_path=element.accessibility_path,
            )
            elements.append(
                {
                    "element_ref": element_ref,
                    "role": element.role,
                    "name": redact_text(element.name, max_chars=256),
                    "value": self._safe_value(element),
                    "supported_actions": sorted(element.supported_actions),
                }
            )
        artifact = self._artifact(
            capture,
            app_ref=app_ref,
            window_ref=window_ref,
            generation=snapshot.snapshot_generation,
        )
        return {
            "ok": True,
            "session_id": self.session_id,
            "app_ref": app_ref,
            "window_ref": window_ref,
            "snapshot_ref": snapshot.token,
            "snapshot_generation": snapshot.snapshot_generation,
            "mode": mode,
            "elements": elements,
            "artifact": artifact,
        }

    def _capture_target(
        self: ServiceState,
        target: dict[str, Any],
    ) -> tuple[str, str, ObservedWindow] | dict[str, Any]:
        window_ref = str(target.get("window_ref", ""))
        if window_ref:
            window = self._windows.get(window_ref)
            app_ref = self._window_apps.get(window_ref)
            if window is None or app_ref is None:
                return self._refused("cross_session_ref")
            return app_ref, window_ref, window
        app_ref = str(target.get("app_ref", ""))
        app = self._apps.get(app_ref)
        if app is None:
            return self._refused("cross_session_ref")
        matching = [
            (ref, window)
            for ref, window in self._windows.items()
            if window.pid == app.pid
            and window.process_generation == app.process_generation
        ]
        if len(matching) != 1:
            return self._refused(
                "identity_ambiguous" if matching else "identity_incomplete"
            )
        window_ref, window = matching[0]
        return app_ref, window_ref, window

    def _artifact(
        self: ServiceState,
        capture: BackendCapture,
        *,
        app_ref: str,
        window_ref: str,
        generation: int,
    ) -> dict[str, Any] | None:
        if (
            capture.image_bytes is None
            or capture.media_type is None
            or capture.width is None
            or capture.height is None
        ):
            return None
        artifact = self.artifact_store.put_capture(
            capture.image_bytes,
            media_type=capture.media_type,
            width=capture.width,
            height=capture.height,
            scope=ArtifactScope(
                self.session_id,
                app_ref,
                window_ref,
                generation,
            ),
            isolated=capture.isolated,
            annotations=[element.name for element in capture.elements],
        )
        metadata = asdict(artifact)
        metadata.pop("raw_bytes", None)
        return metadata

    @staticmethod
    def _safe_value(element: ObservedElement) -> object | None:
        return DiscoveryMixin._safe_property(element, "value")

    @staticmethod
    def _safe_property(
        element: ObservedElement,
        property_name: str,
    ) -> object | None:
        if element.sensitive_category is not None:
            return "[REDACTED]"
        value = getattr(element, property_name)
        if isinstance(value, str):
            return redact_text(value, max_chars=512)
        return value
