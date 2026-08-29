"""Durable state for approval-bound Office creation jobs."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import final

from .create_contract import creation_error, required_text
from .journal_record import journal_root, read_record, write_record

_STAGE = "office_creation_journal"
_VERSION = 1


def _job_id(value: object) -> str:
    job_id = required_text(value, "job_id")
    if len(job_id) != 32 or any(
        character not in "0123456789abcdef" for character in job_id
    ):
        raise creation_error("creation job id is invalid")
    return job_id


@final
class CreationJobJournal:
    """Persist one exact creation proposal, export, and rollback receipt."""

    def __init__(self, office_home: Path) -> None:
        self._root = journal_root(
            Path(office_home) / "creation-jobs",
            _STAGE,
        )

    def path_for(self, job_id: str) -> Path:
        return self._root / f"{_job_id(job_id)}.json"

    def create(self, payload: Mapping[str, object]) -> None:
        job_id = _job_id(payload.get("job_id"))
        path = self.path_for(job_id)
        if read_record(path, _STAGE) is not None:
            raise creation_error("creation job already exists")
        write_record(
            path,
            {
                "version": _VERSION,
                "kind": "office_create",
                "job_id": job_id,
                "state": "approval_requested",
                "approval": dict(payload),
            },
            _STAGE,
        )

    def latest(self, job_id: str) -> dict[str, object]:
        return read_record(self.path_for(job_id), _STAGE) or {}

    def require_approval(
        self,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        job_id = _job_id(payload.get("job_id"))
        record = self.latest(job_id)
        if (
            record.get("version") != _VERSION
            or record.get("kind") != "office_create"
            or record.get("job_id") != job_id
            or record.get("state") not in {"approval_requested", "exported"}
            or record.get("approval") != dict(payload)
        ):
            raise creation_error("durable creation job does not match approval")
        return record

    def mark_exported(
        self,
        payload: Mapping[str, object],
        result: Mapping[str, object],
    ) -> None:
        record = self.require_approval(payload)
        if record.get("state") == "exported":
            if record.get("result") != dict(result):
                raise creation_error("durable creation receipt changed")
            return
        write_record(
            self.path_for(_job_id(payload.get("job_id"))),
            {
                **record,
                "state": "exported",
                "export": result.get("export"),
                "result": dict(result),
            },
            _STAGE,
        )

    def mark_rolled_back(
        self,
        job_id: str,
        rollback: Mapping[str, object],
    ) -> None:
        record = self.latest(job_id)
        if (
            record.get("kind") != "office_create"
            or record.get("job_id") != job_id
            or record.get("state") not in {"exported", "rolled_back"}
        ):
            raise creation_error("creation job is not rollback-ready")
        if record.get("state") == "rolled_back":
            if record.get("rollback") != dict(rollback):
                raise creation_error("durable creation rollback changed")
            return
        write_record(
            self.path_for(job_id),
            {
                **record,
                "state": "rolled_back",
                "rollback": dict(rollback),
            },
            _STAGE,
        )


__all__ = ["CreationJobJournal"]
