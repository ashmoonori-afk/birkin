"""Canonical approval records projected into workspace snapshots."""

from __future__ import annotations

import json
from typing import TypeGuard, cast

from birkin import approvals, config, risk, store

from .contracts import json_object


def _is_object_mapping(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def approval_items(
    durable_items: tuple[dict[str, object], ...] = (),
) -> tuple[dict[str, object], ...]:
    """Compose durable approval events with canonical authority records."""

    records: list[dict[str, object]] = list(approvals.reviewable_pending())
    for status in ("approved", "rejected", "error", "expired"):
        records.extend(store.list_resolved(status))
    records.sort(key=lambda record: str(record.get("created") or ""))
    canonical = tuple(approval_item(record) for record in records)
    canonical_ids = {str(item["id"]) for item in canonical}
    return (
        tuple(
            item
            for item in durable_items
            if str(item.get("id") or "") not in canonical_ids
        )
        + canonical
    )


def approval_policy() -> dict[str, object]:
    """Project requested config separately from its validated effective value."""

    requested: object = None
    path = config.config_path()
    if path.is_file():
        try:
            raw = json_object(
                cast(object, json.loads(path.read_text(encoding="utf-8"))),
                "config",
            )
            requested = raw.get("auto_approve")
        except (json.JSONDecodeError, OSError):
            requested = None
    effective: list[object] = config.load_config().get("auto_approve") or []
    return {
        "requested": {"auto_approve": requested},
        "effective": {"auto_approve": list(effective)},
        "pending_requests": [
            str(record.get("id")) for record in approvals.reviewable_pending()
        ],
    }


def approval_item(record: dict[str, object]) -> dict[str, object]:
    status = str(record.get("status") or "pending")
    category = str(record.get("category") or "")
    payload = record.get("payload")
    sealed = _is_object_mapping(payload) and (
        (
            category == "operation"
            and isinstance(payload.get("digest"), str)
            and bool(payload["digest"])
        )
        or (
            category == "office_create"
            and isinstance(payload.get("creation_digest"), str)
            and bool(payload["creation_digest"])
        )
        or (
            category == "office_job"
            and isinstance(payload.get("proposal_digest"), str)
            and bool(payload["proposal_digest"])
        )
        or (
            category == "office_rollback"
            and isinstance(payload.get("receipt_hmac"), str)
            and bool(payload["receipt_hmac"])
        )
    )
    item: dict[str, object] = {
        "id": str(record.get("id") or ""),
        "summary": str(record.get("title") or category or "Approval"),
        "description": str(record.get("description") or ""),
        "category": category,
        "status": status,
        "risk": risk.risk_for(category),
        "sealed": sealed,
        "decided": status != "pending",
        "kind": "approval",
        "ui_state": "action_needed" if status == "pending" else _ui_state(status),
        "created": str(record.get("created") or ""),
    }
    resolved_at = record.get("resolved_at")
    if isinstance(resolved_at, str) and resolved_at:
        item["resolved_at"] = resolved_at
    if _is_object_mapping(payload):
        for field in (
            "destination",
            "source_filename",
            "authority_digest",
            "rejection_result",
        ):
            value = payload.get(field)
            if isinstance(value, str) and value:
                item[field] = value
        requester = payload.get("proposer")
        if isinstance(requester, str) and requester:
            item["requester"] = requester
        overwrite_approved = payload.get("overwrite_approved")
        if isinstance(overwrite_approved, bool):
            item["overwrite_approved"] = overwrite_approved
    expires_at = record.get("expires_at")
    if isinstance(expires_at, str) and expires_at:
        item["expires_at"] = expires_at
    for field in (
        "failure_code",
        "follow_up_approval_id",
        "retry_of_approval_id",
    ):
        value = record.get(field)
        if isinstance(value, str) and value:
            item[field] = value
    overwrite_retry = record.get("overwrite_retry")
    if isinstance(overwrite_retry, bool):
        item["overwrite_retry"] = overwrite_retry
    return item


def _ui_state(status: str) -> str:
    if status == "approved":
        return "succeeded"
    if status == "rejected":
        return "blocked"
    return "failed"
