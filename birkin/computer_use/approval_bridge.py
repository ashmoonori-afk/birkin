"""Durable exact-retry grants through Birkin's existing approval flow."""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .. import approvals, config, store

_GRANT_ID = re.compile(r"^cu_grant_[A-Za-z0-9_-]{16,}$")


@dataclass(frozen=True, slots=True)
class ProposedGrant:
    review_id: str
    grant_id: str


def _grant_path(grant_id: str) -> Path:
    if not _GRANT_ID.fullmatch(grant_id):
        raise ValueError("invalid Computer Use grant id")
    root = config.birkin_home() / "computer-use" / "grants"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{grant_id}.json"


class ApprovalBridge:
    def __init__(
        self,
        *,
        session_id: str,
        cfg: dict[str, Any] | None = None,
        ttl_seconds: int = 300,
    ):
        self.session_id = session_id
        self.cfg = dict(cfg or config.load_config())
        self.ttl_seconds = ttl_seconds

    def propose(
        self,
        *,
        intent_digest: str,
        prior_receipt: str,
        action: str,
    ) -> ProposedGrant:
        grant_id = "cu_grant_" + secrets.token_urlsafe(18)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.ttl_seconds)
        payload = {
            "version": 1,
            "grant_id": grant_id,
            "session_id": self.session_id,
            "intent_digest": intent_digest,
            "prior_receipt": prior_receipt,
            "action": action,
            "expires_at": expires_at.isoformat(),
        }
        explicit_cfg = dict(self.cfg)
        auto = explicit_cfg.get("auto_approve")
        if isinstance(auto, list):
            explicit_cfg["auto_approve"] = [
                item for item in auto if item != "computer_use"
            ]
        proposed = approvals.propose(
            category="computer_use",
            title=f"Approve foreground Computer Use {action}",
            description=(
                "Grant one exact foreground retry after a documented "
                "background delivery failure."
            ),
            payload=payload,
            cfg=explicit_cfg,
            origin="computer_use",
        )
        return ProposedGrant(
            review_id=str(proposed["id"]),
            grant_id=grant_id,
        )

    def consume(
        self,
        grant_id: str,
        *,
        intent_digest: str,
        prior_receipt: str,
    ) -> str | None:
        try:
            path = _grant_path(grant_id)
        except ValueError:
            return "foreground_approval_mismatch"
        try:
            with store.file_lock(path):
                grant = store._read_json(path, None)
                if not isinstance(grant, dict):
                    return "foreground_approval_required"
                if grant.get("state") == "consumed":
                    return "foreground_approval_expired"
                if (
                    grant.get("session_id") != self.session_id
                    or grant.get("intent_digest") != intent_digest
                    or grant.get("prior_receipt") != prior_receipt
                ):
                    return "foreground_approval_mismatch"
                try:
                    expires = datetime.fromisoformat(str(grant["expires_at"]))
                except (KeyError, TypeError, ValueError):
                    return "foreground_approval_mismatch"
                if expires.tzinfo is None:
                    return "foreground_approval_mismatch"
                if datetime.now(timezone.utc) >= expires:
                    grant["state"] = "expired"
                    store._write_json(path, grant)
                    return "foreground_approval_expired"
                if grant.get("state") != "approved":
                    return "foreground_approval_required"
                grant["state"] = "consumed"
                grant["consumed_at"] = datetime.now(timezone.utc).isoformat()
                store._write_json(path, grant)
        except store.FileLockTimeout:
            return "foreground_approval_required"
        return None


def approve_payload(payload: dict[str, Any]) -> str:
    """Approve an exact future retry; never execute the mutation."""
    required = {
        "grant_id",
        "session_id",
        "intent_digest",
        "prior_receipt",
        "action",
        "expires_at",
    }
    if payload.get("version") != 1 or not required <= payload.keys():
        raise ValueError("invalid Computer Use approval payload")
    grant_id = str(payload["grant_id"])
    path = _grant_path(grant_id)
    grant = {
        key: payload[key]
        for key in (
            "version",
            "grant_id",
            "session_id",
            "intent_digest",
            "prior_receipt",
            "action",
            "expires_at",
        )
    }
    grant["state"] = "approved"
    grant["approved_at"] = datetime.now(timezone.utc).isoformat()
    with store.file_lock(path):
        store._write_json(path, grant)
    return f"Granted one exact future Computer Use retry ({grant_id})."
