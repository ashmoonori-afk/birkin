"""Typed background-job state and atomic receipt persistence."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
EventKind = Literal[
    "queued",
    "running",
    "progress",
    "succeeded",
    "failed",
    "cancelled",
]


@dataclass(frozen=True)
class JobEvent:
    """One ordered transition in a background job receipt."""

    sequence: int
    kind: EventKind
    message: str
    at: float


@dataclass(frozen=True)
class JobSnapshot:
    """Immutable public view of one background job."""

    id: str
    name: str
    status: JobStatus
    result: str | None
    error: str | None
    events: tuple[JobEvent, ...]


@dataclass
class JobRecord:
    id: str
    name: str
    status: JobStatus = "queued"
    result: str | None = None
    error: str | None = None
    events: list[JobEvent] = field(default_factory=list)


def snapshot(record: JobRecord) -> JobSnapshot:
    return JobSnapshot(
        id=record.id,
        name=record.name,
        status=record.status,
        result=record.result,
        error=record.error,
        events=tuple(record.events),
    )


def append_event(
    record: JobRecord,
    kind: EventKind,
    message: str,
) -> None:
    record.events.append(
        JobEvent(
            sequence=len(record.events),
            kind=kind,
            message=message,
            at=time.time(),
        )
    )


def persist(record: JobRecord, receipt_dir: Path) -> None:
    value = {
        "id": record.id,
        "name": record.name,
        "status": record.status,
        "result": record.result,
        "error": record.error,
        "events": [
            {
                "sequence": event.sequence,
                "kind": event.kind,
                "message": event.message,
                "at": event.at,
            }
            for event in record.events
        ],
    }
    destination = receipt_dir / f"{record.id}.json"
    temporary = receipt_dir / f".{record.id}.tmp"
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(destination)
