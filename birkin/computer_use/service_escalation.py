"""Approval-bound escalation from semantic background delivery."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .receipts import receipt_ref
from .service_types import ServiceState


class EscalationMixin:
    def _background_unsupported(
        self: ServiceState,
        request: dict[str, Any],
        *,
        digest: str,
        idempotency_key: str,
        intent_digest: str,
    ) -> dict[str, Any]:
        foreground_supported = str(request["action"]) in self.backend.foreground_actions
        response = {
            **self._refused("background_delivery_unsupported"),
            "delivery": "background",
            "intent_digest": intent_digest,
        }
        if foreground_supported:
            response["escalation"] = {
                "recommended_delivery": "foreground",
                "approval_required": True,
            }
        response["receipt_ref"] = receipt_ref(response)
        stored_response = dict(response)
        approval: dict[str, str] | None = None
        if foreground_supported and self.approval_bridge is not None:
            proposed = self.approval_bridge.propose(
                intent_digest=intent_digest,
                prior_receipt=response["receipt_ref"],
                action=str(request["action"]),
            )
            approval = {
                "review_id": proposed.review_id,
                "approval_id": proposed.grant_id,
            }
        self.receipts.record(
            session_id=self.session_id,
            idempotency_key=idempotency_key,
            digest=digest,
            response=stored_response,
        )
        if approval is not None:
            response["approval"] = approval
        return response

    @staticmethod
    def intent_digest(request: dict[str, Any]) -> str:
        excluded = {
            "action_id",
            "approval_id",
            "delivery",
            "idempotency_key",
            "prior_background_receipt",
        }
        intent = {key: value for key, value in request.items() if key not in excluded}
        encoded = json.dumps(
            intent,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _foreground_refusal(
        self: ServiceState,
        request: dict[str, Any],
        intent_digest: str,
    ) -> str | None:
        prior_ref = str(request.get("prior_background_receipt") or "")
        prior = self.receipts.get(prior_ref)
        if (
            prior is None
            or prior.response.get("refusal_code") != "background_delivery_unsupported"
            or prior.response.get("intent_digest") != intent_digest
        ):
            return "foreground_evidence_required"
        approval_id = str(request.get("approval_id") or "")
        if not approval_id:
            return "foreground_approval_required"
        if self.approval_bridge is not None and approval_id.startswith("cu_grant_"):
            return self.approval_bridge.consume(
                approval_id,
                intent_digest=intent_digest,
                prior_receipt=prior_ref,
            )
        return self.approvals.consume(
            approval_id,
            intent_digest=intent_digest,
            prior_receipt=prior_ref,
        )
