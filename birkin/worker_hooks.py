"""Persisted, bounded continuations for approval-gated workers."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

WORKERS = (
    "moirai",
    "mnemosyne",
    "neurosis",
    "morpheus",
    "boulder",
    "harness",
    "odyssey",
    "osiris",
)
NO_MODEL_WORKERS = ("mnemosyne",)
PERSISTENCE_OWNER = {"osiris": "boulder"}
_HANDLERS = ("worker.resume.v1",)
_MAX_BYTES = 16_384


class WorkerHookError(ValueError):
    """A persisted worker continuation is unsafe or cannot be dispatched."""


def contract() -> dict[str, Any]:
    """Return the machine-consumed worker authority boundaries."""
    return {
        "workers": WORKERS,
        "no_model": NO_MODEL_WORKERS,
        "persistence_owner": dict(PERSISTENCE_OWNER),
    }


def validate(value: Any) -> dict[str, Any]:
    """Parse a continuation envelope before it enters or leaves the queue."""
    if not isinstance(value, dict) or set(value) != {
        "schema", "handler", "worker", "context",
    }:
        raise WorkerHookError("invalid worker continuation envelope")
    if value.get("schema") != 1:
        raise WorkerHookError("unsupported worker continuation schema")
    handler = value.get("handler")
    if handler not in _HANDLERS:
        raise WorkerHookError("unknown worker continuation handler")
    worker = value.get("worker")
    if worker not in WORKERS:
        raise WorkerHookError(f"unknown worker: {worker}")
    context = value.get("context")
    if not isinstance(context, dict):
        raise WorkerHookError("worker continuation context must be an object")
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise WorkerHookError("worker continuation must be JSON serializable") from exc
    if len(encoded.encode("utf-8")) > _MAX_BYTES:
        raise WorkerHookError("worker continuation exceeds 16 KiB")
    return json.loads(encoded)


def describe(value: Any) -> str:
    continuation = validate(value)
    checkpoint = str(
        continuation["context"].get("checkpoint", "saved checkpoint")
    )
    return f"resume {continuation['worker']} from {checkpoint}"


def dispatch(
    value: Any,
    *,
    on_event: Callable[[dict[str, Any]], None] | None,
) -> str:
    """Dispatch a bounded continuation to the originating worker loop."""
    continuation = validate(value)
    if on_event is None:
        raise WorkerHookError("originating worker is unavailable to resume")
    event = {
        "type": "worker_resume",
        "worker": continuation["worker"],
        "context": continuation["context"],
    }
    on_event(event)
    checkpoint = str(
        continuation["context"].get("checkpoint", "saved checkpoint")
    )
    return f"resumed {continuation['worker']} at {checkpoint}"
