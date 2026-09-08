"""Sequential batch wrapper around canonical single-file Office jobs."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .. import config, store
from .coordinator import OfficeCaller, OfficeCoordinator, OfficeMutationRequest, execute_approved_office_job
from .coordinator_recovery import approved_office_receipt

MAX_FILES = 25
MAX_TOTAL_BYTES = 1024 * 1024 * 1024


def _root() -> Path:
    path = config.birkin_home() / "office" / "batches"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path(batch_id: str) -> Path:
    if re.fullmatch(r"[0-9a-f]{32}", batch_id) is None:
        raise ValueError("batch id is invalid")
    return _root() / f"{batch_id}.json"


def _request(raw: Mapping[str, object]) -> OfficeMutationRequest:
    operations = raw.get("operations")
    if isinstance(operations, (str, bytes)) or not isinstance(operations, Sequence):
        raise ValueError("batch operations must be an array")
    return OfficeMutationRequest(
        request_text=str(raw.get("request", "")), source=raw.get("source", {}),
        outcome=str(raw.get("outcome", "")), operations=tuple(item for item in operations if isinstance(item, Mapping)),
        destination=Path(str(raw.get("destination", ""))), overwrite_approved=raw.get("overwrite_approved") is True,
    )


def _reconcile(batch_id: str) -> tuple[dict[str, object], dict[int, str]]:
    record = store._read_json(_path(batch_id), {})
    requests, plans, results = record.get("requests"), record.get("plans"), record.get("results")
    if (
        not isinstance(requests, list) or not isinstance(plans, list) or not isinstance(results, list)
        or len(requests) != len(plans) or len(results) != len(plans)
    ):
        raise ValueError("batch cannot be resumed because its plans are missing")
    states: dict[int, str] = {}
    changed = False
    for index, result in enumerate(results):
        if not isinstance(result, Mapping) or result.get("status") not in {"failed", "pending", "running"}:
            continue
        plan = plans[index]
        if not isinstance(plan, Mapping):
            continue
        try:
            receipt = json.loads(approved_office_receipt(plan))
            states[index] = str(receipt.get("state", ""))
            if (
                states[index] == "exported"
                and receipt.get("job_id") == plan.get("job_id")
                and receipt.get("authority_digest") == plan.get("authority_digest")
                and receipt.get("rollback") is None
            ):
                results[index] = {"index": index, "status": "succeeded", "receipt": receipt}
                changed = True
        except Exception:
            pass
    succeeded = sum(isinstance(item, Mapping) and item.get("status") == "succeeded" for item in results)
    failed = sum(isinstance(item, Mapping) and item.get("status") == "failed" for item in results)
    pending = len(results) - succeeded - failed
    status = "running" if pending else "succeeded" if succeeded == len(results) else "failed" if succeeded == 0 else "partial_failed"
    if changed or any(record.get(key) != value for key, value in {"succeeded": succeeded, "failed": failed, "pending": pending, "status": status}.items()):
        record.update(succeeded=succeeded, failed=failed, pending=pending, status=status)
        store._write_json(_path(batch_id), record)
    return record, states


def prepare(items: object, caller: OfficeCaller, *, retry_of: str | None = None) -> dict[str, object]:
    if retry_of is not None:
        previous, states = _reconcile(retry_of)
        requests = previous.get("requests", [])
        previous_plans = previous.get("plans", [])
        results = previous.get("results", [])
        selected = [index for index, result in enumerate(results) if isinstance(result, Mapping) and result.get("status") != "succeeded"]
        items = [requests[index] for index in selected]
        coordinator = OfficeCoordinator(caller)
        plans = [
            coordinator.request(_request(requests[index]))
            if states.get(index) in {"failed", "rejected"}
            else previous_plans[index]
            for index in selected
        ]
    if isinstance(items, (str, bytes)) or not isinstance(items, Sequence) or not (
        retry_of is not None and not items or 1 <= len(items) <= MAX_FILES
    ):
        raise ValueError(f"batch must contain between 1 and {MAX_FILES} files")
    raw_items = [dict(item) for item in items if isinstance(item, Mapping)]
    if len(raw_items) != len(items):
        raise ValueError("each batch item must be an object")
    destinations = [str(item.get("destination", "")) for item in raw_items]
    if len(set(destinations)) != len(destinations):
        raise ValueError("batch destinations must be unique")
    total = sum(Path(str(item.get("source", {}).get("uri", ""))).stat().st_size for item in raw_items if isinstance(item.get("source"), Mapping))
    if total > MAX_TOTAL_BYTES:
        raise ValueError("batch source bytes exceed the 1 GiB limit")
    if retry_of is None:
        coordinator = OfficeCoordinator(caller)
        plans = [coordinator.request(_request(item)) for item in raw_items]
    return {"batch_id": uuid.uuid4().hex, "retry_of": retry_of, "mode": "sequential", "source_bytes": total, "requests": raw_items, "plans": plans}


def execute(payload: dict[str, Any], *, approval_id: str | None, on_transition=None) -> str:
    plans = payload.get("plans")
    if not isinstance(plans, list) or (not plans and payload.get("retry_of") is None):
        raise ValueError("batch plans are required")
    batch_id = str(payload.get("batch_id", ""))
    path = _path(batch_id)
    requests = payload.get("requests")
    if not isinstance(requests, list) or len(requests) != len(plans):
        raise ValueError("batch requests do not match plans")
    approval = store.get_pending(approval_id) if approval_id else None
    if approval is not None and (
        approval.get("category") != "office_batch"
        or approval.get("status") != "executing"
        or approval.get("payload") != payload
    ):
        raise ValueError("batch approval does not own this frozen scope")
    results: list[dict[str, object]] = [
        {"index": index, "status": "pending"} for index in range(len(plans))
    ]

    def checkpoint() -> dict[str, object]:
        succeeded = sum(item["status"] == "succeeded" for item in results)
        failed = sum(item["status"] == "failed" for item in results)
        pending = len(results) - succeeded - failed
        record: dict[str, object] = {
            "batch_id": batch_id, "retry_of": payload.get("retry_of"), "requests": requests, "plans": plans,
            "results": results, "succeeded": succeeded, "failed": failed, "pending": pending,
            "status": "running" if pending else "succeeded" if succeeded == len(results) else "failed" if succeeded == 0 else "partial_failed",
        }
        store._write_json(path, record)
        return record

    record = checkpoint()
    for index, plan in enumerate(plans):
        if not isinstance(plan, dict):
            results[index] = {"index": index, "status": "failed", "reason": "invalid plan"}
            record = checkpoint()
            continue
        results[index] = {"index": index, "status": "running"}
        checkpoint()
        try:
            receipt = execute_approved_office_job(plan, approval_id=approval_id, on_transition=on_transition)
            results[index] = {"index": index, "status": "succeeded", "receipt": json.loads(receipt)}
        except Exception as exc:
            results[index] = {"index": index, "status": "failed", "reason": f"{type(exc).__name__}: {exc}"[:500]}
        finally:
            record = checkpoint()
    parent_id = payload.get("retry_of")
    ancestors: set[str] = set()
    while isinstance(parent_id, str) and parent_id not in ancestors:
        ancestors.add(parent_id)
        parent, _ = _reconcile(parent_id)
        parent_id = parent.get("retry_of")
    return json.dumps(record, ensure_ascii=False, sort_keys=True)


def list_batches(limit: int = 20) -> list[dict[str, object]]:
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    records = []
    for path in sorted(_root().glob("*.json"), key=lambda item: item.stat().st_mtime_ns, reverse=True)[:limit]:
        raw = store._read_json(path, {})
        if isinstance(raw, dict):
            try:
                reconciled, _ = _reconcile(path.stem)
            except (OSError, TypeError, ValueError):
                reconciled = raw
            records.append(reconciled)
    return records


__all__ = ["execute", "list_batches", "prepare"]
