"""Fsynced append-only authority for one-shot approval execution."""

from __future__ import annotations

import hashlib
import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, final

from typing_extensions import override

from . import config
from .approval_execution_codec import (
    JSONValue,
    JournalCodecError,
    canonical,
    json_mapping,
)
from .approval_execution_state import (
    JournalPhase,
    JournalSnapshot,
    JournalStateError,
    snapshot,
)
from .private_storage import (
    harden_private_directory,
    harden_private_file,
    read_private_text,
)

_VERSION: Final = 1
_RESULT_LIMIT: Final = 2000


@dataclass(frozen=True, slots=True)
class JournalCorruptionError(RuntimeError):
    detail: str

    @override
    def __str__(self) -> str:
        return self.detail


def authority_digest(record: Mapping[str, object]) -> str:
    authority = {
        key: record.get(key)
        for key in ("id", "created", "category", "origin", "payload", "continuation")
    }
    return hashlib.sha256(canonical(authority)).hexdigest()


@final
class ExecutionJournal:
    """Append and verify one hash-chained execution history."""

    def __init__(self, approval_id: str) -> None:
        if not config.pending_dir().name or len(approval_id) != 12:
            raise JournalCorruptionError("invalid approval execution identity")
        self.path = config.pending_dir() / f"{approval_id}.execution.jsonl"
        self.approval_id = approval_id

    def arm(
        self,
        authority_digest: str,
        category: str,
        payload: Mapping[str, JSONValue],
    ) -> None:
        if self.path.exists():
            raise JournalCorruptionError("approval execution journal already exists")
        self._append(
            {
                "kind": JournalPhase.ARMED.value,
                "authority_digest": authority_digest,
                "category": category,
                "payload": dict(payload),
            }
        )

    def ready(self) -> None:
        self._transition(JournalPhase.ARMED, JournalPhase.READY)

    def helper_started(
        self,
        *,
        owner_pid: int,
        owner_token: str = "local",
        owner_generation: str | None = None,
    ) -> None:
        snapshot = self.load()
        if snapshot.phase not in {JournalPhase.READY, JournalPhase.HELPER_STARTED}:
            raise JournalCorruptionError("approval execution helper cannot start now")
        self._append(
            {
                "kind": JournalPhase.HELPER_STARTED.value,
                "owner_pid": owner_pid,
                "owner_token": owner_token,
                "owner_generation": owner_generation,
            }
        )

    def commit_attempt(
        self,
        *,
        owner_pid: int,
        owner_token: str = "local",
        owner_generation: str | None = None,
    ) -> None:
        snapshot = self.load()
        if snapshot.phase not in {JournalPhase.READY, JournalPhase.HELPER_STARTED}:
            raise JournalCorruptionError("approval execution attempt cannot commit now")
        if snapshot.owner_token is not None and snapshot.owner_token != owner_token:
            raise JournalCorruptionError("approval execution helper ownership differs")
        self._append(
            {
                "kind": JournalPhase.ATTEMPT_COMMITTED.value,
                "owner_pid": owner_pid,
                "owner_token": owner_token,
                "owner_generation": owner_generation,
            }
        )

    def resume_office(self) -> None:
        snapshot = self.load()
        if (
            snapshot.category != "office_job"
            or snapshot.phase is not JournalPhase.ATTEMPT_COMMITTED
        ):
            raise JournalCorruptionError("Office approval execution cannot resume now")
        self._append({"kind": JournalPhase.READY.value})

    def retry_cron(self) -> None:
        snapshot = self.load()
        if (
            snapshot.category != "cron"
            or snapshot.phase is not JournalPhase.RETRYABLE_FAILURE
        ):
            raise JournalCorruptionError("cron approval execution cannot retry now")
        self._append({"kind": JournalPhase.READY.value})

    def succeeded(self, result: str) -> None:
        self._transition(
            JournalPhase.ATTEMPT_COMMITTED,
            JournalPhase.SUCCEEDED,
            {"result": result[:_RESULT_LIMIT]},
        )

    def failed(self, error: str) -> None:
        self._transition(
            JournalPhase.ATTEMPT_COMMITTED,
            JournalPhase.FAILED,
            {"error": error[:_RESULT_LIMIT]},
        )

    def retryable_cron_failure(self, error: str) -> None:
        if self.load().category != "cron":
            raise JournalCorruptionError("only cron failures can be retried")
        self._transition(
            JournalPhase.ATTEMPT_COMMITTED,
            JournalPhase.RETRYABLE_FAILURE,
            {"error": error[:_RESULT_LIMIT]},
        )

    def outcome_unknown(self) -> None:
        self._transition(
            JournalPhase.ATTEMPT_COMMITTED,
            JournalPhase.ACTION_OUTCOME_UNKNOWN,
            {"error": "helper died after committing the action attempt"},
        )

    def load(self) -> JournalSnapshot:
        try:
            raw = read_private_text(self.path)
        except FileNotFoundError as exc:
            raise JournalCorruptionError(
                "approval execution journal is missing"
            ) from exc
        if not raw or not raw.endswith("\n"):
            raise JournalCorruptionError(
                "approval execution journal has an incomplete line"
            )
        previous = ""
        events: list[dict[str, JSONValue]] = []
        for sequence, line in enumerate(raw.splitlines(), start=1):
            try:
                value = json_mapping(line)
            except JournalCodecError as exc:
                raise JournalCorruptionError(str(exc)) from exc
            if value.get("version") != _VERSION or value.get("sequence") != sequence:
                raise JournalCorruptionError(
                    "approval execution journal sequence is invalid"
                )
            if value.get("approval_id") != self.approval_id:
                raise JournalCorruptionError(
                    "approval execution journal identity differs"
                )
            if value.get("previous_digest") != previous:
                raise JournalCorruptionError(
                    "approval execution journal chain is broken"
                )
            digest = value.get("digest")
            if not isinstance(digest, str):
                raise JournalCorruptionError(
                    "approval execution journal digest is invalid"
                )
            body = dict(value)
            del body["digest"]
            expected = hashlib.sha256(canonical(body)).hexdigest()
            if not secrets_equal(digest, expected):
                raise JournalCorruptionError("approval execution journal was tampered")
            previous = digest
            events.append(value)
        try:
            return snapshot(events)
        except JournalStateError as exc:
            raise JournalCorruptionError(str(exc)) from exc

    def _transition(
        self,
        expected: JournalPhase,
        target: JournalPhase,
        fields: Mapping[str, JSONValue] | None = None,
    ) -> None:
        if self.load().phase is not expected:
            raise JournalCorruptionError(
                f"approval execution cannot move from {self.load().phase.value} to {target.value}"
            )
        self._append({"kind": target.value, **(fields or {})})

    def _append(self, fields: Mapping[str, JSONValue]) -> None:
        harden_private_directory(self.path.parent)
        previous = ""
        sequence = 1
        if self.path.exists():
            snapshot_raw = read_private_text(self.path)
            if not snapshot_raw.endswith("\n"):
                raise JournalCorruptionError(
                    "approval execution journal has an incomplete line"
                )
            try:
                last = json_mapping(snapshot_raw.splitlines()[-1])
            except JournalCodecError as exc:
                raise JournalCorruptionError(str(exc)) from exc
            digest = last.get("digest")
            prior_sequence = last.get("sequence")
            if not isinstance(digest, str) or not isinstance(prior_sequence, int):
                raise JournalCorruptionError(
                    "approval execution journal tail is invalid"
                )
            previous = digest
            sequence = prior_sequence + 1
        body: dict[str, JSONValue] = {
            "version": _VERSION,
            "sequence": sequence,
            "approval_id": self.approval_id,
            "previous_digest": previous,
            **fields,
        }
        event = {**body, "digest": hashlib.sha256(canonical(body)).hexdigest()}
        flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.path, flags, 0o600)
        try:
            data = canonical(event) + b"\n"
            view = memoryview(data)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        harden_private_file(self.path)


def secrets_equal(left: str, right: str) -> bool:
    return secrets.compare_digest(left, right)
