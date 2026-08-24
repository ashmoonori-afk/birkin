"""States and typed collaborators for the Office job state machine."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Protocol

from .export_policy import ExportRequest


class OfficeJobState(str, Enum):
    input_captured = "input_captured"
    outcome_declared = "outcome_declared"
    operations_proposed = "operations_proposed"
    preview_ready = "preview_ready"
    approval_requested = "approval_requested"
    approved = "approved"
    executed = "executed"
    validated = "validated"
    exported = "exported"
    rejected = "rejected"
    failed = "failed"


class OfficeJobRunner(Protocol):
    def preview(self, *, source: Mapping[str, object], format_name: str,
                operations: Sequence[Mapping[str, object]]) -> dict[str, object]: ...
    def execute(self, *, source: Mapping[str, object], format_name: str,
                operations: Sequence[Mapping[str, object]], draft_name: str) -> dict[str, object]: ...
    def validate(self, *, artifact: Mapping[str, object]) -> dict[str, object]: ...
    def publish(self, *, artifact: Mapping[str, object], output_name: str) -> dict[str, object]: ...
    def export(self, *, artifact: Mapping[str, object], request: ExportRequest) -> Mapping[str, object]: ...
    def rollback_export(self, receipt: Mapping[str, object]) -> Mapping[str, object]: ...
