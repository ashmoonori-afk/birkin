"""Drag, wait, and no-raise focus action helpers."""

from __future__ import annotations

from typing import Any

from .bindings import BindingError
from .models import ElementTarget
from .service_types import ServiceState


class ActionMixin:
    def _drag(
        self: ServiceState,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            start = ElementTarget(**request["start"])
            end = ElementTarget(**request["end"])
            start_binding = self.bindings.resolve_element(start)
            end_binding = self.bindings.resolve_element(end)
        except BindingError as exc:
            return self._refused(exc.code)
        except (KeyError, TypeError):
            return self._refused("identity_incomplete")
        if (
            start.app_ref != end.app_ref
            or start.window_ref != end.window_ref
            or start.snapshot_ref != end.snapshot_ref
        ):
            return self._refused("identity_mismatch")
        delegated = dict(request)
        delegated["target"] = request["start"]
        delegated["secondary_accessibility_identity"] = (
            end_binding.accessibility_identity
        )
        result = self._mutate(delegated)
        if result.get("mutation_dispatched"):
            result["secondary_accessibility_identity"] = (
                end_binding.accessibility_identity
            )
            result["start_accessibility_identity"] = (
                start_binding.accessibility_identity
            )
        return result
