"""Canonical approval records projected into workspace snapshots."""

from __future__ import annotations

import json
from typing import Any, cast

from birkin import approvals, config, risk, store


def approval_items(
    durable_items: tuple[dict[str, object], ...] = (),
) -> tuple[dict[str, object], ...]:
    """Compose durable approval events with canonical authority records."""

    records: list[dict[str, Any]] = list(approvals.reviewable_pending())
    for status in ("approved", "rejected", "error", "expired"):
        records.extend(store.list_resolved(status))
    records.sort(key=lambda record: str(record.get("created") or ""))
    canonical = tuple(approval_item(record) for record in records)
    canonical_ids = {str(item["id"]) for item in canonical}
    return tuple(
        item for item in durable_items if str(item.get("id") or "") not in canonical_ids
    ) + canonical


def approval_policy() -> dict[str, object]:
    """Project requested config separately from its validated effective value."""

    requested: object = None
    path = config.config_path()
    if path.is_file():
        try:
            raw = cast(object, json.loads(path.read_text(encoding="utf-8")))
            if isinstance(raw, dict):
                requested = cast(dict[object, object], raw).get("auto_approve")
        except (json.JSONDecodeError, OSError):
            requested = None
    effective = config.load_config().get("auto_approve") or []
    return {
        "requested": {"auto_approve": requested},
        "effective": {"auto_approve": list(effective)},
        "pending_requests": [
            str(record.get("id")) for record in approvals.reviewable_pending()
        ],
    }


def approval_item(record: dict[str, Any]) -> dict[str, object]:
    status = str(record.get("status") or "pending")
    category = str(record.get("category") or "")
    payload = record.get("payload")
    sealed = (
        category == "operation"
        and isinstance(payload, dict)
        and isinstance(payload.get("digest"), str)
        and bool(payload["digest"])
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
    return item


def _ui_state(status: str) -> str:
    if status == "approved":
        return "succeeded"
    if status == "rejected":
        return "blocked"
    return "failed"
