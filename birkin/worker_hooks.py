"""Persisted, bounded continuations for approval-gated workers."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime
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
_HANDLERS = ("worker.resume.v1", "moirai.resume.v1")
_MAX_BYTES = 16_384
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_STEP_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43,128}")
_MOIRAI_CONTEXT = {
    "action_id",
    "run_id",
    "worker_id",
    "step_id",
    "question_digest",
    "expected_actor",
    "expected_capability",
    "expires_at",
    "resume_token",
    "input_schema_version",
    "previous_state_digest",
}


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
    if handler == "moirai.resume.v1":
        _validate_moirai(worker, context)
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise WorkerHookError("worker continuation must be JSON serializable") from exc
    if len(encoded.encode("utf-8")) > _MAX_BYTES:
        raise WorkerHookError("worker continuation exceeds 16 KiB")
    return json.loads(encoded)


def _validate_moirai(worker: Any, context: dict[str, Any]) -> None:
    if worker != "moirai" or set(context) != _MOIRAI_CONTEXT:
        raise WorkerHookError("invalid moirai continuation envelope")
    if not _pending_id(context["action_id"]):
        raise WorkerHookError("invalid moirai action id")
    if not _bounded_text(context["run_id"], 128):
        raise WorkerHookError("invalid moirai run id")
    if context["worker_id"] != "main":
        raise WorkerHookError("invalid moirai worker id")
    if not isinstance(context["step_id"], str) or not _STEP_ID.fullmatch(
        context["step_id"]
    ):
        raise WorkerHookError("invalid moirai step id")
    for name in ("question_digest", "previous_state_digest"):
        value = context[name]
        if not isinstance(value, str) or not _HEX_64.fullmatch(value):
            raise WorkerHookError(f"invalid moirai {name.replace('_', ' ')}")
    for name in ("expected_actor", "expected_capability"):
        if not _bounded_text(context[name], 128):
            raise WorkerHookError(f"invalid moirai {name.replace('_', ' ')}")
    try:
        expiry = datetime.fromisoformat(context["expires_at"])
    except (TypeError, ValueError) as exc:
        raise WorkerHookError("invalid moirai expiry") from exc
    if expiry.tzinfo is None:
        raise WorkerHookError("invalid moirai expiry")
    token = context["resume_token"]
    if not isinstance(token, str) or not _TOKEN.fullmatch(token):
        raise WorkerHookError("invalid moirai resume token")
    if context["input_schema_version"] != 1:
        raise WorkerHookError("unsupported moirai input schema")


def _pending_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 12
        and all(char in "0123456789abcdef" for char in value)
    )


def _bounded_text(value: Any, limit: int) -> bool:
    return isinstance(value, str) and 0 < len(value) <= limit


def describe(value: Any) -> str:
    continuation = validate(value)
    if continuation["handler"] == "moirai.resume.v1":
        context = continuation["context"]
        return (
            f"resume moirai run {context['run_id']} "
            f"at {context['worker_id']}/{context['step_id']}"
        )
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
    if continuation["handler"] != "worker.resume.v1":
        raise WorkerHookError("moirai continuations require durable dispatch")
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
