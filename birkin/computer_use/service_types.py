"""Internal structural type shared by Computer Use service components."""

from __future__ import annotations

from typing import Any, Protocol

from .approval import ForegroundApprovalStore
from .approval_bridge import ApprovalBridge
from .artifacts import ArtifactStore
from .backends.base import ComputerUseBackend
from .bindings import BindingStore
from .cancellation import CancellationRegistry
from .events import EventStream
from .models import ObservedApp, ObservedWindow
from .receipts import ReceiptStore
from .session_policy import SessionCapability


class ServiceState(Protocol):
    backend: ComputerUseBackend
    artifact_store: ArtifactStore
    session_id: str
    bindings: BindingStore
    receipts: ReceiptStore
    approvals: ForegroundApprovalStore
    approval_bridge: ApprovalBridge | None
    cancellations: CancellationRegistry
    events: EventStream
    session_capability: SessionCapability
    _apps: dict[str, ObservedApp]
    _windows: dict[str, ObservedWindow]
    _app_refs: dict[tuple[int, str, str], str]
    _window_refs: dict[tuple[int, str, str, int], str]
    _window_apps: dict[str, str]

    @staticmethod
    def _refused(code: str) -> dict[str, Any]: ...

    def _mutate(self, request: dict[str, Any]) -> dict[str, Any]: ...

    def _app_ref(self, window: ObservedWindow) -> str | None: ...

    def _capture_target(
        self,
        target: dict[str, Any],
    ) -> tuple[str, str, ObservedWindow] | dict[str, Any]: ...

    def _artifact(self, *args: Any, **kwargs: Any) -> dict[str, Any] | None: ...

    def _safe_value(self, element: Any) -> object | None: ...

    def _safe_property(
        self,
        element: Any,
        property_name: str,
    ) -> object | None: ...

    @staticmethod
    def _cancelled() -> dict[str, Any]: ...

    @staticmethod
    def intent_digest(request: dict[str, Any]) -> str: ...

    def _background_unsupported(
        self,
        request: dict[str, Any],
        *,
        digest: str,
        idempotency_key: str,
        intent_digest: str,
    ) -> dict[str, Any]: ...

    def _foreground_refusal(
        self,
        request: dict[str, Any],
        intent_digest: str,
    ) -> str | None: ...

    def _response(
        self,
        request: dict[str, Any],
        *,
        dispatched: bool,
        delivery: str,
        verification: Any,
        observed: object | None,
        focus_preserved: bool,
        restoration: dict[str, object] | None,
    ) -> dict[str, Any]: ...

    @staticmethod
    def _fail(response: dict[str, Any], code: str) -> None: ...
