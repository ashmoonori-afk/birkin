"""Crash-safe append-only snapshots for Office jobs."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, cast, final

from .errors import DocumentError, DocumentErrorCode

if TYPE_CHECKING:
    from .job import OfficeJob
    from .job_types import OfficeJobRunner


_SERIALIZED_FIELDS = frozenset(
    {
        "job_id",
        "format_name",
        "source",
        "state",
        "history",
        "outcome",
        "operations",
        "preview",
        "approval",
        "approved_digest",
        "execution",
        "artifact",
        "validation",
        "publication",
        "export",
        "rollback",
        "failure",
    }
)
_TERMINAL_STATE_VALUES = frozenset({"exported", "rejected", "failed"})


def snapshot_job(job: OfficeJob) -> dict[str, object]:
    """Copy every durable OfficeJob field into a JSON-shaped snapshot."""
    return {
        "job_id": job._job_id,
        "format_name": job._format_name,
        "source": deepcopy(job._source),
        "state": job._state.value,
        "history": [state.value for state in job._history],
        "outcome": job._outcome,
        "operations": deepcopy(job._operations),
        "preview": deepcopy(job._preview),
        "approval": deepcopy(job._approval),
        "approved_digest": job._approved_digest,
        "execution": deepcopy(job._execution),
        "artifact": deepcopy(job._artifact),
        "validation": deepcopy(job._validation),
        "publication": deepcopy(job._publication),
        "export": deepcopy(job._export),
        "rollback": deepcopy(job._rollback),
        "failure": deepcopy(job._failure),
    }


def receipt_job(job: OfficeJob) -> dict[str, object]:
    """Copy caller-visible job state into a stable receipt."""
    operations: list[dict[str, object]] | None = None
    if job._outcome is not None:
        operations = deepcopy(job._operations) if job._operations else None
    return {
        "job_id": job._job_id,
        "format": job._format_name,
        "state": job._state.value,
        "history": [state.value for state in job._history],
        "outcome": job._outcome,
        "operations": operations,
        "preview": deepcopy(job._preview),
        "approval": deepcopy(job._approval),
        "execution": deepcopy(job._execution),
        "validation": deepcopy(job._validation),
        "publication": deepcopy(job._publication),
        "export": deepcopy(job._export),
        "rollback": deepcopy(job._rollback),
    }


def _error(message: str) -> DocumentError:
    return DocumentError(
        DocumentErrorCode.PRECONDITION_FAILED,
        "office_job_journal",
        message,
    )


def _required_text(snapshot: Mapping[str, object], field: str) -> str:
    value = snapshot.get(field)
    if not isinstance(value, str) or not value:
        raise _error(f"snapshot field {field!r} must be a non-empty string")
    return value


def _optional_text(snapshot: Mapping[str, object], field: str) -> str | None:
    value = snapshot.get(field)
    if value is not None and not isinstance(value, str):
        raise _error(f"snapshot field {field!r} must be a string or null")
    return value


def _required_mapping(
    snapshot: Mapping[str, object], field: str
) -> dict[str, object]:
    value = snapshot.get(field)
    if not isinstance(value, Mapping):
        raise _error(f"snapshot field {field!r} must be an object")
    return deepcopy(dict(cast("Mapping[str, object]", value)))


def _optional_mapping(
    snapshot: Mapping[str, object], field: str
) -> dict[str, object] | None:
    value = snapshot.get(field)
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise _error(f"snapshot field {field!r} must be an object or null")
    return deepcopy(dict(cast("Mapping[str, object]", value)))


def restore_job(
    snapshot: Mapping[str, object], *, runner: OfficeJobRunner
) -> OfficeJob:
    """Parse an untrusted snapshot and bind a live runner without serializing it."""
    from .job import OfficeJob
    from .job_types import OfficeJobState

    if frozenset(snapshot) != _SERIALIZED_FIELDS:
        raise _error("snapshot fields do not match the OfficeJob schema")
    state_text = _required_text(snapshot, "state")
    history_value = snapshot.get("history")
    if not isinstance(history_value, Sequence) or isinstance(history_value, str):
        raise _error("snapshot field 'history' must be an array")
    try:
        state = OfficeJobState(state_text)
        history = [OfficeJobState(item) for item in history_value if isinstance(item, str)]
    except ValueError as exc:
        raise _error("snapshot contains an unknown OfficeJob state") from exc
    if len(history) != len(history_value) or not history or history[-1] is not state:
        raise _error("snapshot history must end at its current state")
    operations_value = snapshot.get("operations")
    if not isinstance(operations_value, Sequence) or isinstance(operations_value, str):
        raise _error("snapshot field 'operations' must be an array")
    if not all(isinstance(item, Mapping) for item in operations_value):
        raise _error("snapshot operations must contain only objects")
    operations = [
        deepcopy(dict(cast("Mapping[str, object]", item))) for item in operations_value
    ]
    job = OfficeJob(
        job_id=_required_text(snapshot, "job_id"),
        format_name=_required_text(snapshot, "format_name"),
        source=_required_mapping(snapshot, "source"),
        runner=runner,
    )
    job._state = state
    job._history = history
    job._outcome = _optional_text(snapshot, "outcome")
    job._operations = operations
    job._preview = _optional_mapping(snapshot, "preview")
    job._approval = _optional_mapping(snapshot, "approval")
    job._approved_digest = _optional_text(snapshot, "approved_digest")
    job._execution = _optional_mapping(snapshot, "execution")
    job._artifact = _optional_mapping(snapshot, "artifact")
    job._validation = _optional_mapping(snapshot, "validation")
    job._publication = _optional_mapping(snapshot, "publication")
    job._export = _optional_mapping(snapshot, "export")
    job._rollback = _optional_mapping(snapshot, "rollback")
    job._failure = _optional_mapping(snapshot, "failure")
    return job


@final
class OfficeJobJournal:
    """One append-only JSONL stream per job beneath an Office workspace."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)

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
        descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        os.chmod(path, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8", newline="\n") as handle:
            _ = handle.write(record + "\n")
            handle.flush()
            os.fsync(handle.fileno())

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
