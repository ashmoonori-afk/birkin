"""Durable ordered event journal and idempotent command receipts."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import cast, final

from .. import procreg, store
from .contracts import (
    PROTOCOL_VERSION,
    CommandIdConflict,
    JsonValue,
    StaleCursor,
    WorkspaceCommand,
    valid_identifier,
)
from .records import CommandReceipt, WorkspaceEvent
from .journal_receipts import ReceiptStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _secure_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def _secure_append(path: Path, text: str) -> None:
    descriptor = os.open(
        path,
        os.O_APPEND | os.O_CREAT | os.O_WRONLY,
        0o600,
    )
    os.chmod(path, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
        _ = handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


@final
class WorkspaceJournal:
    def __init__(self, root: Path, session_id: str) -> None:
        self.session_id = valid_identifier(session_id, "session_id")
        self.root = root / self.session_id
        self.events_path = self.root / "events.jsonl"
        self.receipts_dir = self.root / "receipts"
        self.lock_path = self.root / "journal"
        _secure_directory(root)
        _secure_directory(self.root)
        _secure_directory(self.receipts_dir)
        self._receipts = ReceiptStore(self.receipts_dir)

    def _read_events(self) -> list[WorkspaceEvent]:
        if not self.events_path.is_file():
            return []
        events: list[WorkspaceEvent] = []
        for line in self.events_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw = cast(object, json.loads(line))
            events.append(WorkspaceEvent.from_json(raw))
        return events

    def _append_unlocked(
        self,
        event_type: str,
        *,
        actor_id: str,
        command_id: str,
        payload: dict[str, JsonValue],
    ) -> WorkspaceEvent:
        events = self._read_events()
        cursor = events[-1].cursor + 1 if events else 1
        event = WorkspaceEvent(
            protocol_version=PROTOCOL_VERSION,
            session_id=self.session_id,
            cursor=cursor,
            event_id=uuid.uuid4().hex,
            type=event_type,
            timestamp=_now(),
            actor_id=actor_id,
            command_id=command_id,
            payload=payload,
        )
        _secure_append(
            self.events_path,
            json.dumps(event.to_json(), ensure_ascii=False) + "\n",
        )
        return event

    def accept(
        self,
        command: WorkspaceCommand,
        *,
        actor_id: str,
    ) -> tuple[CommandReceipt, bool]:
        actor = valid_identifier(actor_id, "actor_id")
        with store.file_lock(self.lock_path):
            existing = self._receipts.read(command.command_id)
            if existing is not None:
                if existing.fingerprint != command.fingerprint():
                    raise CommandIdConflict(
                        f"command id {command.command_id!r} reused with new payload"
                    )
                if existing.state != "accepted":
                    return existing.as_duplicate(), False
                owner_pid = self._receipts.owner_pid(command.command_id)
                if procreg.pid_alive(owner_pid):
                    return existing.as_duplicate(), False
                events = self._read_events()
                started = any(
                    event.command_id == command.command_id
                    and event.type == "command.started"
                    for event in events
                )
                if started:
                    failed = self._append_unlocked(
                        "command.failed",
                        actor_id=existing.actor_id,
                        command_id=existing.command_id,
                        payload={
                            "error": "command interrupted by process restart"
                        },
                    )
                    completed = replace(
                        existing,
                        state="failed",
                        result_event_cursor=failed.cursor,
                    )
                    self._receipts.write(completed)
                    self._receipts.clear_owner(command.command_id)
                    return completed.as_duplicate(), False
                return existing.as_duplicate(), True
            events = self._read_events()
            orphan = next(
                (
                    event
                    for event in events
                    if event.command_id == command.command_id
                    and event.type == "command.accepted"
                ),
                None,
            )
            if orphan is not None:
                fingerprint = orphan.payload.get("fingerprint")
                if fingerprint != command.fingerprint():
                    raise CommandIdConflict(
                        f"command id {command.command_id!r} reused with new payload"
                    )
                receipt = CommandReceipt(
                    protocol_version=PROTOCOL_VERSION,
                    command_id=command.command_id,
                    session_id=self.session_id,
                    actor_id=orphan.actor_id,
                    accepted_cursor=orphan.cursor,
                    state="accepted",
                    result_event_cursor=None,
                    fingerprint=command.fingerprint(),
                )
                self._receipts.write(receipt)
                self._receipts.write_owner(command.command_id)
                return receipt.as_duplicate(), True
            current = events[-1].cursor if events else 0
            if command.expected_cursor != current:
                raise StaleCursor(current)
            accepted = self._append_unlocked(
                "command.accepted",
                actor_id=actor,
                command_id=command.command_id,
                payload={
                    "command_type": command.type,
                    "fingerprint": command.fingerprint(),
                },
            )
            receipt = CommandReceipt(
                protocol_version=PROTOCOL_VERSION,
                command_id=command.command_id,
                session_id=self.session_id,
                actor_id=actor,
                accepted_cursor=accepted.cursor,
                state="accepted",
                result_event_cursor=None,
                fingerprint=command.fingerprint(),
            )
            self._receipts.write(receipt)
            self._receipts.write_owner(command.command_id)
            return receipt, True

    def append(
        self,
        event_type: str,
        *,
        actor_id: str,
        command_id: str,
        payload: dict[str, JsonValue],
    ) -> WorkspaceEvent:
        with store.file_lock(self.lock_path):
            return self._append_unlocked(
                event_type,
                actor_id=valid_identifier(actor_id, "actor_id"),
                command_id=valid_identifier(command_id, "command_id"),
                payload=payload,
            )

    def complete(
        self,
        receipt: CommandReceipt,
        *,
        state: str,
        result_cursor: int,
    ) -> CommandReceipt:
        completed = replace(
            receipt,
            state=state,
            result_event_cursor=result_cursor,
            duplicate=False,
        )
        with store.file_lock(self.lock_path):
            self._receipts.write(completed)
            self._receipts.clear_owner(receipt.command_id)
        return completed

    def events(self, *, after: int = 0) -> tuple[WorkspaceEvent, ...]:
        if isinstance(after, bool) or after < 0:
            raise ValueError("after must be a non-negative integer")
        with store.file_lock(self.lock_path):
            return tuple(event for event in self._read_events() if event.cursor > after)

    def cursor(self) -> int:
        events = self.events()
        return events[-1].cursor if events else 0
