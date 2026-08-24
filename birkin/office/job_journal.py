"""Crash-safe append-only snapshots for Office jobs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, cast, final

from .errors import DocumentError, DocumentErrorCode
from .job_serialization import (
    OfficeJobSnapshot,
    receipt_job as _receipt_job,
    restore_job as _restore_job,
    snapshot_job,
)
from .path_security import directory_identity, sync_directory

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .job import OfficeJob
    from .job_types import OfficeJobRunner


_TERMINAL_STATE_VALUES = frozenset({"exported", "rejected", "failed"})


def _error(message: str, *, retryable: bool = False) -> DocumentError:
    return DocumentError(
        DocumentErrorCode.PRECONDITION_FAILED,
        "office_job_journal",
        message,
        retryable=retryable,
    )


def receipt_job(job: OfficeJobSnapshot) -> dict[str, object]:
    """Copy caller-visible Office job state into a stable receipt."""
    return _receipt_job(job)


def restore_job(
    snapshot: Mapping[str, object], *, runner: OfficeJobRunner
) -> OfficeJob:
    """Restore one durable snapshot using the concrete OfficeJob factory."""
    from .job import OfficeJob

    return _restore_job(snapshot, runner=runner, job_factory=OfficeJob)


@final
class OfficeJobJournal:
    """One append-only JSONL stream per job beneath an Office workspace."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        created = not self.root.exists()
        try:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self.root, 0o700)
            self._root_identity = directory_identity(self.root)
            if created:
                sync_directory(
                    self.root.parent, directory_identity(self.root.parent)
                )
        except OSError as exc:
            raise _error("job journal root is unavailable", retryable=True) from exc

    def path_for(self, job_id: str) -> Path:
        if not job_id or Path(job_id).name != job_id or job_id in {".", ".."}:
            raise _error("job_id is not safe for a journal path")
        return self.root / f"{job_id}.jsonl"

    def append(self, job: OfficeJob) -> None:
        path = self.path_for(job._job_id)
        record = json.dumps(
            snapshot_job(job),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        try:
            descriptor = os.open(
                path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600
            )
            with os.fdopen(
                descriptor, "a", encoding="utf-8", newline="\n"
            ) as handle:
                os.chmod(path, 0o600)
                _ = handle.write(record + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            sync_directory(self.root, self._root_identity)
        except OSError as exc:
            raise _error("job snapshot durability failed", retryable=True) from exc

    def _complete(self, job_id: str) -> tuple[dict[str, object], ...]:
        path = self.path_for(job_id)
        if not path.is_file():
            raise _error(f"job {job_id!r} has no durable snapshot")
        try:
            content = path.read_bytes()
            complete = content.split(b"\n")[:-1]
            if not complete:
                raise _error(f"job {job_id!r} has no complete snapshot")
            snapshots: list[dict[str, object]] = []
            for line in complete:
                if not line:
                    raise _error(f"job {job_id!r} contains an empty snapshot")
                raw = cast(object, json.loads(line.decode("utf-8")))
                if not isinstance(raw, dict):
                    raise _error(f"job {job_id!r} snapshot must be an object")
                snapshots.append(dict(cast("dict[str, object]", raw)))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise _error(f"job {job_id!r} contains a malformed complete snapshot") from exc
        return tuple(snapshots)

    def _latest(self, job_id: str) -> dict[str, object]:
        return self._complete(job_id)[-1]

    def restore(self, job_id: str, *, runner: OfficeJobRunner) -> OfficeJob:
        restored = tuple(
            restore_job(snapshot, runner=runner) for snapshot in self._complete(job_id)
        )
        if any(job._job_id != job_id for job in restored):
            raise _error("journal path and snapshot job_id do not match")
        job = restored[-1]
        job._journal = self
        return job

    def _listed(self, *, terminal: bool) -> tuple[str, ...]:
        job_ids: list[str] = []
        for path in self.root.glob("*.jsonl"):
            snapshot = self._latest(path.stem)
            state = snapshot.get("state")
            if not isinstance(state, str):
                raise _error(f"job {path.stem!r} snapshot state must be a string")
            if (state in _TERMINAL_STATE_VALUES) is terminal:
                job_ids.append(path.stem)
        return tuple(sorted(job_ids))

    def list_terminal(self) -> tuple[str, ...]:
        return self._listed(terminal=True)

    def list_incomplete(self) -> tuple[str, ...]:
        return self._listed(terminal=False)
