"""Pure state machine for a single Office document job."""

from __future__ import annotations

import hashlib
import importlib
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timezone
from typing import Protocol, cast, final, runtime_checkable

from .artifact_serialization import canonical_json
from .errors import DocumentError, DocumentErrorCode
from .export_policy import ExportRequest
from .job_types import OfficeJobRunner as OfficeJobRunner
from .job_types import OfficeJobState as OfficeJobState


class OfficeJobJournalSink(Protocol):
    def append(self, job: OfficeJob) -> None: ...


@runtime_checkable
class _JobJournalModule(Protocol):
    def snapshot_job(self, job: OfficeJob) -> dict[str, object]: ...
    def restore_job(
        self, snapshot: Mapping[str, object], *, runner: OfficeJobRunner
    ) -> OfficeJob: ...
    def receipt_job(self, job: OfficeJob) -> dict[str, object]: ...


def _job_journal() -> _JobJournalModule:
    module = importlib.import_module("birkin.office.job_journal")
    if not isinstance(module, _JobJournalModule):
        raise RuntimeError("Office job journal is unavailable")
    return module


_TERMINAL_STATES = {
    OfficeJobState.exported, OfficeJobState.rejected, OfficeJobState.failed
}


@final
class OfficeJob:
    def __init__(self, *, job_id: str, format_name: str, source: Mapping[str, object],
                 runner: OfficeJobRunner,
                 journal: OfficeJobJournalSink | None = None) -> None:
        self._job_id = job_id
        self._format_name = format_name
        self._source = deepcopy(dict(source))
        self._runner = runner
        self._journal = journal
        self._state = OfficeJobState.input_captured
        self._history = [self._state]
        self._outcome: str | None = None
        self._operations: list[dict[str, object]] = []
        self._preview: dict[str, object] | None = None
        self._approval: dict[str, object] | None = None
        self._approved_digest: str | None = None
        self._execution: dict[str, object] | None = None
        self._artifact: dict[str, object] | None = None
        self._validation: dict[str, object] | None = None
        self._publication: dict[str, object] | None = None
        self._export: dict[str, object] | None = None
        self._rollback: dict[str, object] | None = None
        self._failure: dict[str, object] | None = None
        if self._journal is not None:
            self._journal.append(self)

    def to_dict(self) -> dict[str, object]:
        return _job_journal().snapshot_job(self)

    @classmethod
    def from_dict(cls, snapshot: Mapping[str, object], *, runner: OfficeJobRunner) -> OfficeJob:
        return _job_journal().restore_job(snapshot, runner=runner)

    @property
    def state(self) -> OfficeJobState:
        return self._state

    @property
    def history(self) -> tuple[OfficeJobState, ...]:
        return tuple(self._history)

    def declare_outcome(self, outcome: str) -> None:
        self._require(OfficeJobState.input_captured)
        self._outcome = outcome
        self._enter(OfficeJobState.outcome_declared)

    def propose_operations(self, operations: Sequence[Mapping[str, object]]) -> None:
        self._require(OfficeJobState.outcome_declared)
        if not operations:
            raise self._error(DocumentErrorCode.INVALID_INPUT, "operations must not be empty")
        self._operations = [deepcopy(dict(operation)) for operation in operations]
        self._enter(OfficeJobState.operations_proposed)

    def build_preview(self) -> dict[str, object]:
        self._require(OfficeJobState.operations_proposed)
        preview = self._runner.preview(
            source=deepcopy(self._source),
            format_name=self._format_name,
            operations=self._operation_snapshot(),
        )
        source_sha256 = preview.get("source_sha256")
        if not isinstance(source_sha256, str):
            raise self._error(
                DocumentErrorCode.PRECONDITION_FAILED,
                "preview requires source_sha256",
            )
        self._preview = deepcopy(preview)
        self._enter(OfficeJobState.preview_ready)
        return deepcopy(preview)

    def request_approval(self) -> dict[str, object]:
        self._require(OfficeJobState.preview_ready)
        if self._preview is None:
            raise self._error(DocumentErrorCode.PRECONDITION_FAILED,
                              "preview is unavailable")
        source_sha256 = self._preview.get("source_sha256")
        if not isinstance(source_sha256, str):
            raise self._error(
                DocumentErrorCode.PRECONDITION_FAILED,
                "preview requires source_sha256",
            )
        self._enter(OfficeJobState.approval_requested)
        return {
            "job_id": self._job_id,
            "format": self._format_name,
            "outcome": self._outcome,
            "operations": deepcopy(self._operations),
            "preview": deepcopy(self._preview),
            "proposal_digest": self._proposal_digest(),
            "source_sha256": source_sha256,
        }

    def approve(self, *, actor: str) -> None:
        self._require(OfficeJobState.approval_requested)
        digest = self._proposal_digest()
        self._approved_digest = digest
        self._approval = {
            "decision": "approved",
            "actor": actor,
            "at": self._now(),
            "proposal_digest": digest,
        }
        self._enter(OfficeJobState.approved)

    def reject(self, *, actor: str, reason: str) -> None:
        self._require(OfficeJobState.approval_requested)
        self._approval = {
            "decision": "rejected",
            "actor": actor,
            "at": self._now(),
            "proposal_digest": self._proposal_digest(),
            "reason": reason,
        }
        self._enter(OfficeJobState.rejected)

    def execute(self) -> dict[str, object]:
        if self._state is OfficeJobState.approval_requested:
            raise self._error(DocumentErrorCode.POLICY_DENIED,
                              "execution requires approval")
        self._require(OfficeJobState.approved)
        if self._approved_digest != self._proposal_digest():
            raise self._error(DocumentErrorCode.PRECONDITION_FAILED,
                              "approved proposal has changed")
        execution = self._runner.execute(
            source=deepcopy(self._source),
            format_name=self._format_name,
            operations=self._operation_snapshot(),
            draft_name=f"{self._job_id}.draft.{self._format_name}",
        )
        artifact = execution.get("artifact")
        sha256 = execution.get("sha256")
        if not isinstance(artifact, Mapping) or not isinstance(sha256, str):
            raise self._error(DocumentErrorCode.PRECONDITION_FAILED,
                              "execution requires artifact and sha256")
        self._execution = deepcopy(execution)
        artifact_mapping = cast("Mapping[str, object]", artifact)
        self._artifact = deepcopy(dict(artifact_mapping))
        self._enter(OfficeJobState.executed)
        return deepcopy(execution)

    def validate(self) -> dict[str, object]:
        self._require(OfficeJobState.executed)
        if self._artifact is None:
            raise self._error(DocumentErrorCode.PRECONDITION_FAILED,
                              "executed artifact is unavailable")
        validation = self._runner.validate(artifact=deepcopy(self._artifact))
        if "status" not in validation or "valid" not in validation:
            raise self._error(DocumentErrorCode.PRECONDITION_FAILED,
                              "validation requires status and valid")
        self._validation = deepcopy(validation)
        if validation["status"] == "fail":
            self._enter(OfficeJobState.failed)
        else:
            self._enter(OfficeJobState.validated)
        return deepcopy(validation)

    def publish(self, *, output_name: str) -> dict[str, object]:
        self._require(OfficeJobState.validated)
        if self._artifact is None:
            raise self._error(DocumentErrorCode.PRECONDITION_FAILED,
                              "validated artifact is unavailable")
        publication = self._runner.publish(
            artifact=deepcopy(self._artifact), output_name=output_name
        )
        artifact = publication.get("artifact")
        sha256 = publication.get("sha256")
        if not isinstance(artifact, Mapping) or not isinstance(sha256, str):
            raise self._error(DocumentErrorCode.PRECONDITION_FAILED,
                              "publication requires artifact and sha256")
        self._publication = deepcopy(publication)
        if self._journal is not None:
            self._journal.append(self)
        return deepcopy(publication)

    def export(self, request: ExportRequest) -> dict[str, object]:
        self._require(OfficeJobState.validated)
        if self._publication is None:
            raise self._error(DocumentErrorCode.PRECONDITION_FAILED,
                              "internal publication is unavailable")
        artifact = self._publication.get("artifact")
        if not isinstance(artifact, Mapping):
            raise self._error(DocumentErrorCode.PRECONDITION_FAILED,
                              "internal publication artifact is unavailable")
        artifact_mapping = cast("Mapping[str, object]", artifact)
        receipt = dict(self._runner.export(
            artifact=deepcopy(dict(artifact_mapping)), request=request
        ))
        self._export = deepcopy(receipt)
        self._rollback = None
        self._enter(OfficeJobState.exported)
        return deepcopy(receipt)

    def rollback_export(self) -> dict[str, object]:
        self._require(OfficeJobState.exported)
        if self._export is None:
            raise self._error(DocumentErrorCode.PRECONDITION_FAILED,
                              "export receipt is unavailable")
        receipt = dict(self._runner.rollback_export(deepcopy(self._export)))
        self._rollback = deepcopy(receipt)
        self._enter(OfficeJobState.validated)
        return deepcopy(receipt)

    def receipt(self) -> dict[str, object]:
        return _job_journal().receipt_job(self)

    def fail(self, *, stage: str, message: str) -> None:
        if self._state in _TERMINAL_STATES:
            raise self._error(DocumentErrorCode.PRECONDITION_FAILED,
                              "terminal job cannot transition")
        self._failure = {"stage": stage, "message": message}
        self._enter(OfficeJobState.failed)

    def _require(self, expected: OfficeJobState) -> None:
        if self._state is not expected:
            message = f"{expected.value} required; current state is {self._state.value}"
            raise self._error(DocumentErrorCode.PRECONDITION_FAILED, message)

    def _enter(self, state: OfficeJobState) -> None:
        self._state = state
        self._history.append(state)
        if self._journal is not None:
            self._journal.append(self)

    def _proposal_digest(self) -> str:
        if self._preview is None or self._outcome is None:
            raise self._error(DocumentErrorCode.PRECONDITION_FAILED,
                              "proposal is incomplete")
        source_sha256 = self._preview.get("source_sha256")
        if not isinstance(source_sha256, str):
            raise self._error(
                DocumentErrorCode.PRECONDITION_FAILED,
                "preview requires source_sha256",
            )
        proposal = {
            "operations": self._operations,
            "source_sha256": source_sha256,
            "outcome": self._outcome,
        }
        return hashlib.sha256(canonical_json(proposal).encode("utf-8")).hexdigest()

    def _operation_snapshot(self) -> tuple[Mapping[str, object], ...]:
        return tuple(deepcopy(operation) for operation in self._operations)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _error(code: DocumentErrorCode, message: str) -> DocumentError:
        return DocumentError(code, "office_job", message)
