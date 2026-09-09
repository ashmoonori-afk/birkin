"""Truthful storage, retention, and bounded deletion controls."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from collections.abc import Mapping

from . import config, store
from .m365_connection import status as connection_status
from .office.coordinator_data import canonical_office_home
from .office.errors import DocumentError
from .office.export_helper_retire import retire_authenticated_file
from .office.receipt_auth import RETENTION_DAYS, verified_receipt_window
from .private_storage import read_private_text


def _recovery_items(office: Path) -> list[dict[str, object]]:
    now = datetime.now(timezone.utc)
    items: list[dict[str, object]] = []
    for directory in (office / "jobs", office / "creation-jobs"):
        if not directory.is_dir() or directory.is_symlink():
            continue
        for path in directory.glob("*.jsonl"):
            try:
                record = json.loads(read_private_text(path).splitlines()[-1])
                receipt = record.get("export")
                if not isinstance(receipt, Mapping):
                    continue
                _, expires = verified_receipt_window(receipt, office)
                items.append({
                    "job_id": record.get("job_id"), "expires_at": expires.isoformat(timespec="seconds"),
                    "state": "recoverable" if now < expires else "expired_pending_physical_purge",
                })
            except (DocumentError, IndexError, OSError, TypeError, ValueError):
                continue
    return items


def status(cfg: dict[str, Any] | None = None) -> dict[str, object]:
    settings = cfg or {}
    office = canonical_office_home()
    vault = Path(str(settings.get("vault_path") or config.birkin_home() / "vault")).expanduser().resolve()
    return {
        "connected_account": connection_status(),
        "search_folders": [str((office / "sources").resolve()), str((office / "artifacts" / "incoming").resolve())],
        "provider_transfer": "selected request text and explicitly selected artifact context only; tool output is redacted",
        "memory": {"enabled": bool(settings.get("memory_enabled", True)), "path": str(vault), "deletion": "logical archive; physical vault deletion requires owner action"},
        "retention": {"office_receipts_and_recovery_days": RETENTION_DAYS, "expired_state": "physical purge after recovery expiry", "recovery_items": _recovery_items(office)},
        "storage_classes": {
            "original": {"owner": "user_or_connected_service", "birkin_deletes": False},
            "work_copy": {"owner": "birkin", "deletion": "approved physical deletion"},
            "memory": {"owner": "user", "deletion": "logical archive"},
            "backup": {"owner": "birkin", "deletion": "authenticated physical purge after recovery expiry"},
        },
        "cache": {"office_search": "none", "memory_index": "rebuildable_and_refreshes_on_read"},
        "protections": ["workspace_jail", "external_secret_reference", "output_redaction", "artifact_acl_fingerprint"],
    }


def delete_work_copy(payload: dict[str, object]) -> str:
    office = canonical_office_home().resolve()
    path = Path(str(payload.get("uri", ""))).resolve()
    allowed = (office / "sources", office / "artifacts" / "incoming")
    if not any(path.is_relative_to(root.resolve()) for root in allowed):
        raise PermissionError("only a Birkin-owned imported work copy can be deleted")
    expected = str(payload.get("content_hash", ""))
    if len(expected) != 64 or not retire_authenticated_file(path, expected):
        raise ValueError("work copy is missing or changed")
    receipt = {
        "scope": "work_copy", "uri": str(path), "content_hash": expected,
        "logical_discarded": True, "physical_deleted": True,
        "search_cache_invalidated": "not_applicable_no_office_search_cache",
        "deleted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with store.file_lock(config.data_deletions_path()):
        records = store._read_json(config.data_deletions_path(), [])
        store._write_json(config.data_deletions_path(), [*(records if isinstance(records, list) else []), receipt])
    return json.dumps(receipt, ensure_ascii=False, sort_keys=True)


__all__ = ["delete_work_copy", "status"]
