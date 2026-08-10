"""Bounded background jobs with durable ordered receipts."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from queue import Queue
from types import TracebackType
from typing import TYPE_CHECKING

from .background_receipts import (
    EventKind,
    JobEvent,
    JobRecord,
    JobSnapshot,
    append_event,
    persist,
    snapshot,
)

if TYPE_CHECKING:
    from typing_extensions import Self

__all__ = ["BackgroundBroker", "JobContext", "JobEvent", "JobSnapshot"]


class JobContext:
    """Progress reporter available to a running task."""

    def __init__(self, broker: BackgroundBroker, job_id: str) -> None:
        self._broker = broker
        self._job_id = job_id

    def progress(self, message: str) -> None:
        self._broker._progress(self._job_id, message)


JobTask = Callable[[JobContext], str]


class _TaskErrorCapture:
    """Capture ordinary task failures without swallowing process interrupts."""

    def __init__(self) -> None:
        self.error: Exception | None = None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        if isinstance(exc_value, Exception):
            self.error = exc_value
            return True
        return False


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
        self._lock = threading.RLock()
        self._records: dict[str, JobRecord] = {}
        self._tasks: dict[str, JobTask] = {}
        self._completed: dict[str, threading.Event] = {}
        self._queue: Queue[str | None] = Queue()
        self._queue_slots = threading.BoundedSemaphore(max_workers)
        self._workers = tuple(
            threading.Thread(
                target=self._worker,
                name=f"birkin-background-{index + 1}",
                daemon=True,
            )
            for index in range(max_workers)
        )
        self._closed = False
        self._stop_sent = False
        for worker in self._workers:
            worker.start()

    def __enter__(self) -> Self:
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
            if not self._queue_slots.acquire(blocking=False):
                raise RuntimeError("background queue is full")
            job_id = uuid.uuid4().hex
            record = JobRecord(id=job_id, name=job_name)
            self._records[job_id] = record
            self._tasks[job_id] = task
            self._completed[job_id] = threading.Event()
            self._append(record, "queued", job_name)
            self._persist(record)
            self._queue.put_nowait(job_id)
            return self._snapshot(record)

    def get(self, job_id: str) -> JobSnapshot:
        with self._lock:
            return self._snapshot(self._record(job_id))

    def wait(self, job_id: str, *, timeout: float | None = None) -> JobSnapshot:
        with self._lock:
            completed = self._completed.get(job_id)
            if completed is None:
                raise KeyError(job_id)
        if not completed.wait(timeout=timeout):
            raise TimeoutError(f"background job {job_id} timed out")
        return self.get(job_id)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            record = self._record(job_id)
            if record.status != "queued":
                return False
            record.status = "cancelled"
            self._append(record, "cancelled", "cancelled before start")
            self._persist(record)
            self._completed[job_id].set()
            return True

    def close(self, *, wait: bool = True) -> None:
        send_stop = False
        with self._lock:
            if not self._closed:
                self._closed = True
                if not wait:
                    for record in self._records.values():
                        if record.status == "queued":
                            record.status = "cancelled"
                            self._append(
                                record,
                                "cancelled",
                                "cancelled during shutdown",
                            )
                            self._persist(record)
                            self._completed[record.id].set()
            if not self._stop_sent:
                self._stop_sent = True
                send_stop = True
        if send_stop:
            for _worker in self._workers:
                self._queue.put_nowait(None)
        if wait:
            for worker in self._workers:
                worker.join()

    def _worker(self) -> None:
        while True:
            job_id = self._queue.get()
            try:
                if job_id is None:
                    return
                self._queue_slots.release()
                with self._lock:
                    record = self._record(job_id)
                    if record.status == "cancelled":
                        continue
                    task = self._tasks[job_id]
                self._run(job_id, task)
            finally:
                self._queue.task_done()

    def _run(self, job_id: str, task: JobTask) -> None:
        try:
            with self._lock:
                record = self._record(job_id)
                if record.status == "cancelled":
                    return
                record.status = "running"
                self._append(record, "running", "started")
                self._persist(record)

            capture = _TaskErrorCapture()
            result: str | None = None
            with capture:
                value = task(JobContext(self, job_id))
                if not isinstance(value, str):
                    raise TypeError("background task result must be text")
                result = value
            if capture.error is not None:
                with self._lock:
                    record = self._record(job_id)
                    record.status = "failed"
                    record.error = (
                        f"{type(capture.error).__name__}: {capture.error}"
                    )
                    self._append(record, "failed", record.error)
                    self._persist(record)
            elif result is not None:
                with self._lock:
                    record = self._record(job_id)
                    record.status = "succeeded"
                    record.result = result
                    self._append(record, "succeeded", result)
                    self._persist(record)
        except OSError as exc:
            with self._lock:
                record = self._record(job_id)
                record.status = "failed"
                record.error = f"OSError: {exc}"
                self._append(record, "failed", record.error)
        finally:
            self._completed[job_id].set()

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

    def _record(self, job_id: str) -> JobRecord:
        try:
            return self._records[job_id]
        except KeyError as exc:
            raise KeyError(f"unknown background job: {job_id}") from exc

    @staticmethod
    def _snapshot(record: JobRecord) -> JobSnapshot:
        return snapshot(record)

    @staticmethod
    def _append(
        record: JobRecord,
        kind: EventKind,
        message: str,
    ) -> None:
        append_event(record, kind, message)

    def _persist(self, record: JobRecord) -> None:
        persist(record, self._receipt_dir)
