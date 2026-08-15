"""Versioned, redacted Computer Use event stream."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from typing import Any


@dataclass(frozen=True, slots=True)
class ComputerEvent:
    version: int
    sequence: int
    session_id: str
    kind: str
    payload: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "sequence": self.sequence,
            "session_id": self.session_id,
            "kind": self.kind,
            "payload": self.payload,
        }


class EventStream:
    def __init__(
        self,
        *,
        session_id: str,
        emit: Callable[[ComputerEvent], None] | None = None,
    ):
        self.session_id = session_id
        self.emit_callback = emit
        self._sequence = 0
        self._lock = RLock()

    def emit(self, kind: str, payload: dict[str, object]) -> None:
        if self.emit_callback is None:
            return
        with self._lock:
            self._sequence += 1
            event = ComputerEvent(
                version=1,
                sequence=self._sequence,
                session_id=self.session_id,
                kind=kind,
                payload=payload,
            )
            self.emit_callback(event)


def request_summary(request: dict[str, Any]) -> dict[str, object]:
    """Retain control metadata only; raw typed text is never event data."""
    keys = (
        "action",
        "action_id",
        "approval_id",
        "delivery",
        "mode",
        "session_id",
    )
    summary: dict[str, object] = {key: request[key] for key in keys if key in request}
    target = request.get("target")
    if isinstance(target, dict):
        summary["target_refs"] = {
            key: value
            for key, value in target.items()
            if key.endswith("_ref") and isinstance(value, str)
        }
    return summary


def result_summary(result: dict[str, Any]) -> dict[str, object]:
    keys = (
        "ok",
        "status",
        "effect",
        "refusal_code",
        "receipt_ref",
        "snapshot_ref",
        "snapshot_generation",
        "delivery",
        "mutation_dispatched",
        "artifact",
        "focus",
        "restoration",
    )
    summary = {key: result[key] for key in keys if key in result}
    approval = result.get("approval")
    if isinstance(approval, dict):
        for key in ("approval_id", "review_id"):
            value = approval.get(key)
            if isinstance(value, str):
                summary[key] = value
    return summary
