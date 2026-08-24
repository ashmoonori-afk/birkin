"""Persisted event, receipt, and snapshot records."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import final

from .contracts import ProtocolError, json_object, object_mapping

PANEL_KEYS = (
    "tasks_runs",
    "approvals",
    "files_evidence",
    "sessions_history",
    "activity_logs",
    "cron",
    "memory_skills",
    "checkpoints_restore",
    "computer_use",
    "settings_status",
)


def _integer(mapping: dict[str, object], key: str) -> int:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtocolError(f"{key} must be an integer")
    return value


def _string(mapping: dict[str, object], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str):
        raise ProtocolError(f"{key} must be a string")
    return value


@final
@dataclass(frozen=True)
class WorkspaceEvent:
    protocol_version: int
    session_id: str
    cursor: int
    event_id: str
    type: str
    timestamp: str
    actor_id: str
    command_id: str
    payload: dict[str, object]

    def to_json(self) -> dict[str, object]:
        return {
            "protocol_version": self.protocol_version,
            "session_id": self.session_id,
            "cursor": self.cursor,
            "event_id": self.event_id,
            "type": self.type,
            "timestamp": self.timestamp,
            "actor_id": self.actor_id,
            "command_id": self.command_id,
            "payload": self.payload,
        }

    @classmethod
    def from_json(cls, raw: object) -> WorkspaceEvent:
        mapping = object_mapping(raw, "event")
        return cls(
            protocol_version=_integer(mapping, "protocol_version"),
            session_id=_string(mapping, "session_id"),
            cursor=_integer(mapping, "cursor"),
            event_id=_string(mapping, "event_id"),
            type=_string(mapping, "type"),
            timestamp=_string(mapping, "timestamp"),
            actor_id=_string(mapping, "actor_id"),
            command_id=_string(mapping, "command_id"),
            payload=json_object(mapping.get("payload"), "event payload"),
        )


@final
@dataclass(frozen=True)
class CommandReceipt:
    protocol_version: int
    command_id: str
    session_id: str
    actor_id: str
    accepted_cursor: int
    state: str
    result_event_cursor: int | None
    fingerprint: str
    duplicate: bool = False
    transient_result: dict[str, object] | None = None

    def as_duplicate(self) -> CommandReceipt:
        return replace(self, duplicate=True)

    def to_json(self) -> dict[str, object]:
        return {
            "protocol_version": self.protocol_version,
            "command_id": self.command_id,
            "session_id": self.session_id,
            "actor_id": self.actor_id,
            "accepted_cursor": self.accepted_cursor,
            "state": self.state,
            "result_event_cursor": self.result_event_cursor,
            "fingerprint": self.fingerprint,
            "duplicate": self.duplicate,
        }

    def to_public_json(self) -> dict[str, object]:
        return {
            "protocol_version": self.protocol_version,
            "command_id": self.command_id,
            "session_id": self.session_id,
            "actor_id": self.actor_id,
            "accepted_cursor": self.accepted_cursor,
            "state": self.state,
            "result_event_cursor": self.result_event_cursor,
            "duplicate": self.duplicate,
        }

    @classmethod
    def from_json(cls, raw: object) -> CommandReceipt:
        mapping = object_mapping(raw, "receipt")
        result = mapping.get("result_event_cursor")
        if isinstance(result, bool) or not isinstance(result, (int, type(None))):
            raise ProtocolError("result_event_cursor must be an integer or null")
        return cls(
            protocol_version=_integer(mapping, "protocol_version"),
            command_id=_string(mapping, "command_id"),
            session_id=_string(mapping, "session_id"),
            actor_id=_string(mapping, "actor_id"),
            accepted_cursor=_integer(mapping, "accepted_cursor"),
            state=_string(mapping, "state"),
            result_event_cursor=result,
            fingerprint=_string(mapping, "fingerprint"),
        )


@final
@dataclass(frozen=True)
class PanelSummary:
    key: str
    items: tuple[dict[str, object], ...] = ()


@final
@dataclass(frozen=True)
class ComposerState:
    can_send: bool
    can_interrupt: bool = False
    can_resume: bool = False


@final
@dataclass(frozen=True)
class WorkspaceStatus:
    connection: str


@final
@dataclass(frozen=True)
class WorkspaceSnapshot:
    protocol_version: int
    session_id: str
    cursor: int
    panels: tuple[PanelSummary, ...]
    conversation: tuple[dict[str, object], ...]
    composer: ComposerState
    status: WorkspaceStatus
    working_memory: dict[str, object]
    approval_policy: dict[str, object]
    terminals: tuple[dict[str, object], ...]

    def to_json(self) -> dict[str, object]:
        return {
            "protocol_version": self.protocol_version,
            "session_id": self.session_id,
            "cursor": self.cursor,
            "panels": [
                {"key": panel.key, "items": list(panel.items)} for panel in self.panels
            ],
            "conversation": list(self.conversation),
            "composer": {
                "can_send": self.composer.can_send,
                "can_interrupt": self.composer.can_interrupt,
                "can_resume": self.composer.can_resume,
            },
            "status": {"connection": self.status.connection},
            "working_memory": self.working_memory,
            "approval_policy": self.approval_policy,
            "terminals": list(self.terminals),
        }
