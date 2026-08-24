"""Canonical Working Memory projection and workspace mutation authority."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast, final

from birkin import goals, harness
from birkin.workspace.contracts import (
    ProtocolError,
    WorkingMemoryBudgetExceeded,
    WorkingMemoryRevisionConflict,
    object_mapping,
)

_PRIVATE_EVIDENCE_KEYS = frozenset({"path", "absolute_path", "source_path"})
_FIELD_KEYS = frozenset(harness.WORKING_FIELDS)


@final
@dataclass(frozen=True)
class WorkingMemoryMutation:
    op: str
    expected_revision: int
    fields: dict[str, list[str]]

    @classmethod
    def parse(cls, raw: object) -> WorkingMemoryMutation:
        payload = object_mapping(raw, "memory.write payload")
        op = payload.get("op")
        if op not in {"merge", "clear"}:
            raise ProtocolError("memory.write op must be merge or clear")
        expected_keys = (
            {"op", "expected_revision", "fields"}
            if op == "merge"
            else {"op", "expected_revision"}
        )
        if set(payload) != expected_keys:
            raise ProtocolError(f"{op} payload keys do not match the contract")
        revision = payload["expected_revision"]
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise ProtocolError("expected_revision must be a non-negative integer")
        if op == "clear":
            return cls(op="clear", expected_revision=revision, fields={})
        raw_fields = object_mapping(payload["fields"], "memory.write fields")
        if not set(raw_fields) <= _FIELD_KEYS:
            raise ProtocolError("memory.write fields contain unknown keys")
        fields: dict[str, list[str]] = {}
        for key, value in raw_fields.items():
            if not isinstance(value, list):
                raise ProtocolError(
                    f"memory.write field {key} must be an array of strings"
                )
            items = cast(list[object], value)
            if not all(isinstance(item, str) for item in items):
                raise ProtocolError(
                    f"memory.write field {key} must be an array of strings"
                )
            fields[key] = cast(list[str], items)
        return cls(op="merge", expected_revision=revision, fields=fields)


@final
@dataclass(frozen=True)
class WorkingMemoryPreview:
    requested: dict[str, list[str]]
    effective: dict[str, object]


@final
class WorkingMemoryAuthority:
    def __init__(self, session_id: str) -> None:
        self._session_id = harness.validate_working_session_id(session_id)

    def preview(self, mutation: WorkingMemoryMutation) -> WorkingMemoryPreview:
        current = harness.working_state(self._session_id)
        revision = int(current.get("revision") or 0)
        if revision != mutation.expected_revision:
            raise WorkingMemoryRevisionConflict(revision)
        if mutation.op == "clear":
            effective = harness.preview_working_clear(revision)
            return WorkingMemoryPreview(requested={}, effective=effective)
        complete = {
            field: mutation.fields.get(field, []) for field in harness.WORKING_FIELDS
        }
        try:
            effective = harness.preview_working_update(self._session_id, **complete)
        except ValueError as error:
            if "exceeds" in str(error):
                raise WorkingMemoryBudgetExceeded(harness.WORKING_MAX_RENDER) from error
            raise ProtocolError(str(error)) from error
        return WorkingMemoryPreview(requested=mutation.fields, effective=effective)

    def apply(
        self,
        mutation: WorkingMemoryMutation,
        *,
        preview: WorkingMemoryPreview | None = None,
    ) -> WorkingMemoryPreview:
        preview = preview or self.preview(mutation)
        updated_at = str(preview.effective["updated_at"])
        if mutation.op == "clear":
            try:
                effective = harness.clear_working_revisioned(
                    self._session_id,
                    expected_revision=mutation.expected_revision,
                    updated_at=updated_at,
                )
            except ValueError as error:
                current = int(
                    harness.working_state(self._session_id).get("revision") or 0
                )
                raise WorkingMemoryRevisionConflict(current) from error
            return WorkingMemoryPreview(requested={}, effective=effective)
        complete = {
            field: mutation.fields.get(field, []) for field in harness.WORKING_FIELDS
        }
        try:
            effective = harness.update_working(
                self._session_id,
                corrections=complete["corrections"],
                constraints=complete["constraints"],
                decisions=complete["decisions"],
                incomplete=complete["incomplete"],
                evidence=complete["evidence"],
                next_actions=complete["next_actions"],
                expected_revision=mutation.expected_revision,
                updated_at=updated_at,
            )
        except ValueError as error:
            current = int(harness.working_state(self._session_id).get("revision") or 0)
            if current != mutation.expected_revision:
                raise WorkingMemoryRevisionConflict(current) from error
            if "exceeds" in str(error):
                raise WorkingMemoryBudgetExceeded(harness.WORKING_MAX_RENDER) from error
            raise ProtocolError(str(error)) from error
        return WorkingMemoryPreview(requested=preview.requested, effective=effective)


def memory_write_handler(
    session_id: str,
    emit: Callable[[str, dict[str, object]], object],
) -> Callable[[dict[str, object]], dict[str, object]]:
    authority = WorkingMemoryAuthority(session_id)

    def handle(payload: dict[str, object]) -> dict[str, object]:
        mutation = WorkingMemoryMutation.parse(payload)
        preview = authority.preview(mutation)
        _ = emit(
            "working_memory.requested",
            {
                "op": mutation.op,
                "expected_revision": mutation.expected_revision,
                "fields": preview.requested,
                "effective": preview.effective,
            },
        )
        result = authority.apply(mutation, preview=preview)
        _ = emit("working_memory.updated", {"working_memory": result.effective})
        return {"requested": result.requested, "effective": result.effective}

    return handle


def project_working_memory(
    session_id: str,
    files_evidence: tuple[dict[str, object], ...],
) -> dict[str, object]:
    """Combine canonical goal, Working Memory, and checkpoint evidence."""

    state = harness.working_state(session_id)
    goal = goals.get_active(session_id=session_id)
    projected_goal: dict[str, object] | None = None
    if goal is not None:
        projected_goal = {
            "slug": goal.slug,
            "objective": goal.objective,
            "tokens_used": goal.tokens_used,
            "status": goal.status,
        }
    return {
        "revision": int(state.get("revision") or 0),
        "goal": projected_goal,
        "fields": {
            field: list(cast(list[str], state.get(field) or []))
            for field in harness.WORKING_FIELDS
        },
        "files_evidence": [
            {
                key: value
                for key, value in item.items()
                if key.casefold() not in _PRIVATE_EVIDENCE_KEYS
            }
            for item in files_evidence
        ],
    }
