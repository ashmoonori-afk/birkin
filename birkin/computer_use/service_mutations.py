"""Mutation delivery, verification, receipts, and escalation."""

from __future__ import annotations

from typing import Any, cast

from .backends.base import BackendError
from .bindings import BindingError
from .models import DeliveryMode, ElementTarget, MutationCommand
from .policy import (
    classify_mutation,
    command_value,
    semantic_action_supported,
)
from .receipts import receipt_ref, request_digest
from .service_types import ServiceState
from .verification import verify_effect


class MutationMixin:
    def _mutate(
        self: ServiceState,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        digest = request_digest(request)
        idempotency_key = str(request.get("idempotency_key", ""))
        action_id = str(request.get("action_id", ""))
        existing = self.receipts.lookup(
            session_id=self.session_id,
            idempotency_key=idempotency_key,
            digest=digest,
        )
        if existing is not None:
            return existing
        if self.cancellations.is_cancelled(action_id):
            return self._cancelled()
        try:
            target = ElementTarget(**request["target"])
            binding = self.bindings.resolve_element(target)
        except BindingError as exc:
            return self._refused(exc.code)
        except (KeyError, TypeError):
            return self._refused("identity_incomplete")
        before = self.backend.read_element(binding.accessibility_identity)
        if before is None:
            return {
                **self._refused("verification_unavailable"),
                "effect": "unverifiable",
            }
        app = self._apps[target.app_ref]
        window = self._windows[target.window_ref]
        policy = classify_mutation(
            before,
            request,
            app_identity=app.native_identity,
        )
        if policy.status != "allowed":
            response = self._refused(str(policy.refusal_code))
            response["status"] = policy.status
            return response
        authority = self.session_capability.authorize(
            session_id=self.session_id,
            operation=str(request["action"]),
            app_identity=app.native_identity,
            native_window_id=window.native_window_id,
        )
        if authority is not None:
            return self._refused(authority)
        raw_delivery = str(request.get("delivery", "background"))
        if raw_delivery not in {"background", "foreground"}:
            return self._refused("unsupported")
        delivery = cast(DeliveryMode, raw_delivery)
        focus_before = self.backend.focus_state()
        intent = self.intent_digest(request)
        if delivery == "background" and not semantic_action_supported(
            before,
            str(request["action"]),
        ):
            return self._background_unsupported(
                request,
                digest=digest,
                idempotency_key=idempotency_key,
                intent_digest=intent,
            )
        if delivery == "foreground":
            if str(request["action"]) not in self.backend.foreground_actions:
                return self._refused("foreground_delivery_unsupported")
            if not self.backend.can_restore_focus(focus_before):
                return self._refused("foreground_restoration_unavailable")
            refusal = self._foreground_refusal(request, intent)
            if refusal is not None:
                return self._refused(refusal)
        command = MutationCommand(
            action=str(request["action"]),
            accessibility_identity=binding.accessibility_identity,
            delivery=delivery,
            value=command_value(request),
            mode=request.get("mode"),
            secondary_accessibility_identity=(
                str(request["secondary_accessibility_identity"])
                if request.get("secondary_accessibility_identity") is not None
                else None
            ),
            axis=(str(request["axis"]) if request.get("axis") is not None else None),
            amount=(
                float(request["amount"])
                if isinstance(request.get("amount"), (int, float))
                and not isinstance(request.get("amount"), bool)
                else None
            ),
        )
        self.session_capability.consume()
        if self.cancellations.is_cancelled(action_id):
            return self._cancelled()
        restoration: dict[str, object] | None = None
        backend_error: BackendError | None = None
        dispatched = False
        try:
            try:
                dispatched = self.backend.mutate(command)
            except BackendError as exc:
                backend_error = exc
        finally:
            if delivery == "foreground":
                restoration = {
                    "focus_restored": self.backend.restore_focus(focus_before),
                    "released_inputs": list(self.backend.release_inputs()),
                }
        if backend_error is not None:
            if (
                delivery == "background"
                and backend_error.code == "background_delivery_unsupported"
                and not backend_error.effect_possible
            ):
                return self._background_unsupported(
                    request,
                    digest=digest,
                    idempotency_key=idempotency_key,
                    intent_digest=intent,
                )
            focus_after_error = self.backend.focus_state()
            response = {
                **self._refused(backend_error.code),
                "message": backend_error.message,
                "retryable": backend_error.retryable,
                "delivery": delivery,
                "restoration": restoration,
                "focus": {
                    "preserved": focus_before.focus_equivalent(focus_after_error)
                },
            }
            if backend_error.effect_possible:
                response.update(
                    effect="unverifiable",
                    mutation_dispatched=True,
                    refusal_code="unknown_effect",
                )
            response["receipt_ref"] = receipt_ref(response)
            self.receipts.record(
                session_id=self.session_id,
                idempotency_key=idempotency_key,
                digest=digest,
                response=response,
            )
            return response
        after = self.backend.read_element(binding.accessibility_identity)
        focus_after = self.backend.focus_state()
        focus_preserved = focus_before.focus_equivalent(focus_after)
        self.bindings.invalidate_window(target.window_ref)
        verification = verify_effect(
            request.get("predicted_effect", {}),
            before=before,
            after=after,
        )
        predicted_property = str(
            request.get("predicted_effect", {}).get("property", "")
        )
        safe_observed = (
            self._safe_property(after, predicted_property)
            if after is not None and predicted_property in {"value", "name", "role"}
            else None
        )
        response = self._response(
            request,
            dispatched=dispatched,
            delivery=delivery,
            verification=verification,
            observed=safe_observed,
            focus_preserved=focus_preserved,
            restoration=restoration,
        )
        if delivery == "background" and not focus_preserved:
            self._fail(response, "background_state_changed")
        if restoration is not None and not restoration["focus_restored"]:
            self._fail(response, "foreground_restoration_failed")
        if self.cancellations.is_cancelled(action_id):
            self._fail(response, "unknown_effect")
        response["receipt_ref"] = receipt_ref(response)
        self.receipts.record(
            session_id=self.session_id,
            idempotency_key=idempotency_key,
            digest=digest,
            response=response,
        )
        return response

    def _response(
        self: ServiceState,
        request: dict[str, Any],
        *,
        dispatched: bool,
        delivery: str,
        verification: Any,
        observed: object | None,
        focus_preserved: bool,
        restoration: dict[str, object] | None,
    ) -> dict[str, Any]:
        confirmed = dispatched and verification.effect == "confirmed"
        return {
            "ok": confirmed,
            "status": "completed" if confirmed else "failed",
            "effect": verification.effect,
            "delivery": delivery,
            "mutation_dispatched": dispatched,
            "refusal_code": verification.refusal_code,
            "verification": {
                "observed": observed,
                "source": "accessibility_snapshot",
            },
            "focus": {"preserved": focus_preserved},
            "restoration": restoration,
            "actor": self.session_capability.actor,
            "source": self.session_capability.source,
            "action_id": request.get("action_id"),
        }

    @staticmethod
    def _fail(response: dict[str, Any], code: str) -> None:
        response.update(
            ok=False,
            status="failed",
            effect="unverifiable",
            refusal_code=code,
        )

    @staticmethod
    def _cancelled() -> dict[str, Any]:
        return {
            "ok": False,
            "status": "cancelled",
            "effect": "suspected_noop",
            "refusal_code": "cancelled",
            "mutation_dispatched": False,
        }
