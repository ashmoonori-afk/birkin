"""Stateful dispatcher for the typed ``computer_use`` surface."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .approval import ForegroundApprovalStore
from .approval_bridge import ApprovalBridge
from .artifacts import ArtifactError, ArtifactStore
from .backends.base import BackendError, ComputerUseBackend
from .bindings import BindingStore
from .cancellation import CancellationRegistry
from .doctor import doctor_report
from .events import (
    ComputerEvent,
    EventStream,
    request_summary,
    result_summary,
)
from .models import ObservedApp, ObservedWindow
from .receipts import ReceiptStore
from .schema import computer_use_schema
from .schema_validation import request_matches_schema
from .service_actions import ActionMixin
from .service_discovery import DiscoveryMixin
from .service_escalation import EscalationMixin
from .service_mutations import MutationMixin
from .session_policy import SessionCapability

_MUTATIONS = {
    "click",
    "double_click",
    "right_click",
    "middle_click",
    "scroll",
    "type",
}


class ComputerUseService(
    DiscoveryMixin,
    ActionMixin,
    EscalationMixin,
    MutationMixin,
):
    def __init__(
        self,
        *,
        backend: ComputerUseBackend,
        artifact_store: ArtifactStore,
        session_id: str,
        session_capability: SessionCapability | None = None,
        approval_bridge: ApprovalBridge | None = None,
        emit: Callable[[ComputerEvent], None] | None = None,
    ):
        super().__init__()
        self.backend = backend
        self.artifact_store = artifact_store
        self.session_id = session_id
        self.session_capability = session_capability or SessionCapability(
            session_id=session_id,
            actor="agent",
            source="tool",
            allowed_operations=frozenset({*_MUTATIONS, "drag"}),
            allowed_apps=frozenset(),
        )
        self.bindings = BindingStore(
            session_id=session_id,
            backend_id=backend.backend_id,
        )
        self.receipts = ReceiptStore()
        self.cancellations = CancellationRegistry()
        self.approvals = ForegroundApprovalStore()
        self.approval_bridge = approval_bridge
        self.events = EventStream(session_id=session_id, emit=emit)
        self._apps: dict[str, ObservedApp] = {}
        self._windows: dict[str, ObservedWindow] = {}
        self._app_refs: dict[tuple[int, str, str], str] = {}
        self._window_refs: dict[tuple[int, str, str, int], str] = {}
        self._window_apps: dict[str, str] = {}

    def execute(self, request: dict[str, Any]) -> dict[str, Any]:
        valid_request = request_matches_schema(request, computer_use_schema())
        prefix = self._event_prefix(request.get("action")) if valid_request else None
        if prefix is not None:
            self.events.emit(
                f"computer.{prefix}.started",
                request_summary(request),
            )
        try:
            result = self._execute(request)
        except BackendError as exc:
            result = {
                **self._refused(exc.code),
                "message": exc.message,
                "retryable": exc.retryable,
            }
        except ArtifactError as exc:
            result = {
                **self._refused(exc.code),
                "message": exc.message,
                "retryable": False,
            }
        if prefix is not None:
            outcome = "completed" if result.get("ok") else "failed"
            self.events.emit(
                f"computer.{prefix}.{outcome}",
                result_summary(result),
            )
        refusal = result.get("refusal_code")
        if refusal in {
            "permission_denied",
            "permission_required",
            "permission_unknown",
        }:
            self.events.emit(
                "computer.permission.required",
                result_summary(result),
            )
        return result

    def _execute(self, request: dict[str, Any]) -> dict[str, Any]:
        action = request.get("action")
        if request.get("version", 1) != 1:
            return self._refused("unsupported_version")
        if not request_matches_schema(request, computer_use_schema()):
            return self._refused("invalid_request")
        if action == "doctor":
            report = doctor_report(self.backend.probe())
            return {"ok": True, "session_id": self.session_id, **report}
        if action == "list_apps":
            return self._list_apps()
        if not self._session_matches(request):
            return self._refused("cross_session_ref")
        if action == "list_windows":
            return self._list_windows(request)
        if action == "capture":
            return self._capture(request)
        if action == "drag":
            return self._drag(request)
        if action in _MUTATIONS:
            return self._mutate(request)
        return self._refused("unsupported")

    def cancel(self, action_id: str) -> bool:
        return self.cancellations.cancel(action_id)

    @staticmethod
    def _event_prefix(action: object) -> str | None:
        if action == "capture":
            return "capture"
        if action in {*_MUTATIONS, "drag"}:
            return "action"
        return None

    def _session_matches(self, request: dict[str, Any]) -> bool:
        return request.get("session_id") == self.session_id

    @staticmethod
    def _refused(code: str) -> dict[str, Any]:
        return {
            "ok": False,
            "status": "refused",
            "effect": "suspected_noop",
            "refusal_code": code,
            "mutation_dispatched": False,
        }
