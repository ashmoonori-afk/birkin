"""Bounded background jobs with durable ordered receipts."""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
EventKind = Literal[
    "queued", "running", "progress", "succeeded", "failed", "cancelled"
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
class _JobRecord:
    id: str
    name: str
    status: JobStatus = "queued"
    result: str | None = None
    error: str | None = None
    events: list[JobEvent] = field(default_factory=list)


class JobContext:
    """Progress reporter available to a running task."""

    def __init__(self, broker: BackgroundBroker, job_id: str) -> None:
        self._broker = broker
        self._job_id = job_id

    def progress(self, message: str) -> None:
        self._broker._progress(self._job_id, message)


JobTask = Callable[[JobContext], str]


class BackgroundBroker:
    """Run bounded work and persist each transition atomically."""

    def __init__(
        self,
        receipt_dir: str | Path,
        *,
        max_workers: int = 2,
    ) -> None:
        if max_workers <= 0:
            raise ValueError("max_workers must be positive")
        self._receipt_dir = Path(receipt_dir)
        self._receipt_dir.mkdir(parents=True, exist_ok=True)
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="birkin-background",
        )
        self._lock = threading.RLock()
        self._records: dict[str, _JobRecord] = {}
        self._futures: dict[str, Future[None]] = {}
        self._closed = False

    def __enter__(self) -> BackgroundBroker:
        return self

    def __exit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        self.close()

    def submit(self, name: str, task: JobTask) -> JobSnapshot:
        job_name = name.strip()
        if not job_name:
            raise ValueError("job name must not be empty")
        with self._lock:
            if self._closed:
                raise RuntimeError("background broker is closed")
            job_id = uuid.uuid4().hex
            record = _JobRecord(id=job_id, name=job_name)
            self._records[job_id] = record
            self._append(record, "queued", job_name)
            self._persist(record)
            future = self._executor.submit(self._run, job_id, task)
            self._futures[job_id] = future
            return self._snapshot(record)

    def get(self, job_id: str) -> JobSnapshot:
        with self._lock:
            return self._snapshot(self._record(job_id))

    def wait(self, job_id: str, *, timeout: float | None = None) -> JobSnapshot:
        with self._lock:
            future = self._futures.get(job_id)
            if future is None:
                raise KeyError(job_id)
        try:
            future.result(timeout=timeout)
        except CancelledError:
            pass
        return self.get(job_id)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            record = self._record(job_id)
            future = self._futures.get(job_id)
            if record.status != "queued" or future is None:
                return False
            if not future.cancel():
                return False
            record.status = "cancelled"
            self._append(record, "cancelled", "cancelled before start")
            self._persist(record)
            return True

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=True, cancel_futures=False)

    def _run(self, job_id: str, task: JobTask) -> None:
        with self._lock:
            record = self._record(job_id)
            if record.status == "cancelled":
                return
            record.status = "running"
            self._append(record, "running", "started")
            self._persist(record)

        try:
            result = task(JobContext(self, job_id))
            if not isinstance(result, str):
                raise TypeError("background task result must be text")
        except Exception as exc:
            with self._lock:
                record = self._record(job_id)
                record.status = "failed"
                record.error = f"{type(exc).__name__}: {exc}"
                self._append(record, "failed", record.error)
                self._persist(record)
            return

        with self._lock:
            record = self._record(job_id)
            record.status = "succeeded"
            record.result = result
            self._append(record, "succeeded", result)
            self._persist(record)

    def _progress(self, job_id: str, message: str) -> None:
        text = message.strip()
        if not text:
            raise ValueError("progress message must not be empty")
        with self._lock:
            record = self._record(job_id)
            if record.status != "running":
                raise RuntimeError("progress requires a running job")
            self._append(record, "progress", text)
            self._persist(record)

    def _record(self, job_id: str) -> _JobRecord:
        try:
            return self._records[job_id]
        except KeyError as exc:
            raise KeyError(f"unknown background job: {job_id}") from exc

    @staticmethod
    def _snapshot(record: _JobRecord) -> JobSnapshot:
        return JobSnapshot(
            id=record.id,
            name=record.name,
            status=record.status,
            result=record.result,
            error=record.error,
            events=tuple(record.events),
        )

    @staticmethod
    def _append(
        record: _JobRecord,
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

    def _persist(self, record: _JobRecord) -> None:
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
        destination = self._receipt_dir / f"{record.id}.json"
        temporary = self._receipt_dir / f".{record.id}.tmp"
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(destination)
