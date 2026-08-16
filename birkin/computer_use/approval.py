"""One-shot grants for an exact foreground retry."""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class ForegroundGrant:
    intent_digest: str
    prior_receipt: str
    expires_at: float
    state: str = "pending"
    actor: str | None = None


class ForegroundApprovalStore:
    def __init__(
        self,
        *,
        ttl_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._grants: dict[str, ForegroundGrant] = {}

    def propose(self, *, intent_digest: str, prior_receipt: str) -> str:
        approval_id = "cu_approval_" + secrets.token_urlsafe(18)
        self._grants[approval_id] = ForegroundGrant(
            intent_digest=intent_digest,
            prior_receipt=prior_receipt,
            expires_at=self.clock() + self.ttl_seconds,
        )
        return approval_id

    def approve(self, approval_id: str, *, actor: str) -> bool:
        grant = self._grants.get(approval_id)
        if grant is None or grant.state != "pending":
            return False
        if self.clock() >= grant.expires_at:
            self._grants[approval_id] = replace(grant, state="expired")
            return False
        self._grants[approval_id] = replace(
            grant,
            state="approved",
            actor=actor,
        )
        return True

    def consume(
        self,
        approval_id: str,
        *,
        intent_digest: str,
        prior_receipt: str,
    ) -> str | None:
        grant = self._grants.get(approval_id)
        if grant is None or grant.state == "consumed":
            return "foreground_approval_expired"
        if self.clock() >= grant.expires_at:
            self._grants[approval_id] = replace(grant, state="expired")
            return "foreground_approval_expired"
        if grant.state != "approved":
            return "foreground_approval_required"
        if grant.intent_digest != intent_digest or grant.prior_receipt != prior_receipt:
            return "foreground_approval_mismatch"
        self._grants[approval_id] = replace(grant, state="consumed")
        return None
