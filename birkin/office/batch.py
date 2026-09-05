"""Sequential batch wrapper around canonical single-file Office jobs."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .. import config, store
from .coordinator import OfficeCaller, OfficeCoordinator, OfficeMutationRequest, execute_approved_office_job

MAX_FILES = 25
MAX_TOTAL_BYTES = 1024 * 1024 * 1024


def _root() -> Path:
    path = config.birkin_home() / "office" / "batches"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path(batch_id: str) -> Path:
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


def prepare(items: object, caller: OfficeCaller, *, retry_of: str | None = None) -> dict[str, object]:
    if retry_of is not None:
        previous = store._read_json(_path(retry_of), {})
        if not isinstance(previous, dict):
            raise ValueError("batch was not found")
        failed = {int(result["index"]) for result in previous.get("results", []) if isinstance(result, dict) and result.get("status") == "failed"}
        items = [item for index, item in enumerate(previous.get("requests", [])) if index in failed]
    if isinstance(items, (str, bytes)) or not isinstance(items, Sequence) or not 1 <= len(items) <= MAX_FILES:
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
    coordinator = OfficeCoordinator(caller)
    plans = [coordinator.request(_request(item)) for item in raw_items]
    return {"batch_id": uuid.uuid4().hex, "retry_of": retry_of, "mode": "sequential", "source_bytes": total, "requests": raw_items, "plans": plans}


def execute(payload: dict[str, Any], *, approval_id: str | None, on_transition=None) -> str:
    plans = payload.get("plans")
    if not isinstance(plans, list) or not plans:
        raise ValueError("batch plans are required")
    results = []
    for index, plan in enumerate(plans):
        if not isinstance(plan, dict):
            results.append({"index": index, "status": "failed", "reason": "invalid plan"})
            continue
        try:
            receipt = execute_approved_office_job(plan, approval_id=approval_id, on_transition=on_transition)
            results.append({"index": index, "status": "succeeded", "receipt": json.loads(receipt)})
        except Exception as exc:
            results.append({"index": index, "status": "failed", "reason": f"{type(exc).__name__}: {exc}"[:500]})
    succeeded = sum(item["status"] == "succeeded" for item in results)
    record = {
        "batch_id": payload["batch_id"], "retry_of": payload.get("retry_of"), "requests": payload["requests"],
        "results": results, "succeeded": succeeded, "failed": len(results) - succeeded,
        "status": "succeeded" if succeeded == len(results) else "failed" if succeeded == 0 else "partial_failed",
    }
    store._write_json(_path(str(payload["batch_id"])), record)
    return json.dumps(record, ensure_ascii=False, sort_keys=True)


def list_batches(limit: int = 20) -> list[dict[str, object]]:
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    records = []
    for path in sorted(_root().glob("*.json"), key=lambda item: item.stat().st_mtime_ns, reverse=True)[:limit]:
        raw = store._read_json(path, {})
        if isinstance(raw, dict):
            records.append(raw)
    return records


__all__ = ["execute", "list_batches", "prepare"]
