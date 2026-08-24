"""Serialization and restoration boundary for durable Office jobs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Protocol, TypeVar, cast

from .errors import DocumentError, DocumentErrorCode
from .job_types import OfficeJobRunner, OfficeJobState


class OfficeJobSnapshot(Protocol):
    """Durable state exposed by an Office job to the journal boundary."""

    _job_id: str
    _format_name: str
    _source: dict[str, object]
    _state: OfficeJobState
    _history: list[OfficeJobState]
    _outcome: str | None
    _operations: list[dict[str, object]]
    _preview: dict[str, object] | None
    _approval: dict[str, object] | None
    _approved_digest: str | None
    _execution: dict[str, object] | None
    _artifact: dict[str, object] | None
    _validation: dict[str, object] | None
    _publication: dict[str, object] | None
    _export: dict[str, object] | None
    _rollback: dict[str, object] | None
    _failure: dict[str, object] | None


_JobT = TypeVar("_JobT", bound=OfficeJobSnapshot, covariant=True)


class OfficeJobFactory(Protocol[_JobT]):
    """Construct a job restored from durable state with its live runner."""

    def __call__(
        self,
        *,
        job_id: str,
        format_name: str,
        source: Mapping[str, object],
        runner: OfficeJobRunner,
    ) -> _JobT: ...


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


def snapshot_job(job: OfficeJobSnapshot) -> dict[str, object]:
    """Copy every durable Office job field into a JSON-shaped snapshot."""
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


def receipt_job(job: OfficeJobSnapshot) -> dict[str, object]:
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


def _required_mapping(snapshot: Mapping[str, object], field: str) -> dict[str, object]:
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
    snapshot: Mapping[str, object],
    *,
    runner: OfficeJobRunner,
    job_factory: OfficeJobFactory[_JobT],
) -> _JobT:
    """Parse an untrusted snapshot and bind a live runner without serializing it."""
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
    job = job_factory(
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
