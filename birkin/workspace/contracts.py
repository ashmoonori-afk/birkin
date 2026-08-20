"""Strict JSON contracts for the shared Birkin workspace protocol."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast, final

PROTOCOL_VERSION = 1
_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")
_COMMAND_TYPES = {
    "chat.send",
    "chat.steer",
    "chat.interrupt",
    "chat.resume",
    "chat.retry",
    "session.create",
    "session.select",
    "session.rename",
    "session.compact",
    "task.send",
    "task.cancel",
    "approval.answer",
    "question.answer",
    "cron.create",
    "cron.pause",
    "cron.resume",
    "cron.remove",
    "memory.write",
    "memory.link",
    "terminal.create",
    "terminal.input",
    "terminal.resize",
    "terminal.signal",
    "terminal.close",
    "terminal.snapshot",
    "browser.start",
    "browser.navigate",
    "office.create",
    "office.open",
    "file.import",
    "skill.reload",
    "checkpoint.restore",
    "config.set",
    "gateway.restart",
}

JsonValue = object


class ProtocolError(ValueError):
    """A workspace payload violates the protocol boundary."""


class CommandIdConflict(ProtocolError):
    """A command id was reused for different semantics."""


class StaleCursor(ProtocolError):
    """A mutation was based on an obsolete event cursor."""

    current_cursor: int

    def __init__(self, current_cursor: int) -> None:
        super().__init__(f"stale cursor; current cursor is {current_cursor}")
        self.current_cursor = current_cursor


class UnsupportedCommand(ProtocolError):
    """A declared command has no registered authority handler."""


class ConfigMutationRejected(ProtocolError):
    """A requested configuration value failed canonical validation."""


class WorkingMemoryRevisionConflict(ProtocolError):
    """A Working Memory mutation targeted an obsolete revision."""

    current_revision: int

    def __init__(self, current_revision: int) -> None:
        super().__init__(
            f"working memory revision conflict; current revision is {current_revision}"
        )
        self.current_revision = current_revision


class WorkingMemoryBudgetExceeded(ProtocolError):
    """A Working Memory mutation exceeded the canonical render budget."""

    limit: int

    def __init__(self, limit: int) -> None:
        super().__init__(f"working memory exceeds {limit} rendered characters")
        self.limit = limit


class TerminalApprovalRequired(ProtocolError):
    """Canonical shell approval must resolve before a terminal lease exists."""

    approval_id: str

    def __init__(self, approval_id: str) -> None:
        super().__init__(f"shell approval {approval_id} is required before terminal lease")
        self.approval_id = approval_id


class TerminalLeaseRequired(ProtocolError):
    """A terminal mutation did not carry its current live lease proof."""


class TerminalSignalRejected(ProtocolError):
    """A terminal signal is outside the canonical process-tree allowlist."""


class TerminalSequenceRejected(ProtocolError):
    """Terminal input was duplicated or delivered out of order."""


def valid_identifier(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or _ID.fullmatch(value) is None
        or value in {".", ".."}
    ):
        raise ProtocolError(f"{label} must match {_ID.pattern}")
    return value


def _strict_keys(
    raw: Mapping[str, object],
    required: set[str],
    label: str,
) -> None:
    if set(raw) != required:
        missing = sorted(required - set(raw))
        extra = sorted(set(raw) - required)
        raise ProtocolError(f"invalid {label} keys; missing={missing} extra={extra}")


def object_mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ProtocolError(f"{label} must be an object")
    unknown = cast(dict[object, object], value)
    result: dict[str, object] = {}
    for key, item in unknown.items():
        if not isinstance(key, str):
            raise ProtocolError(f"{label} keys must be strings")
        result[key] = item
    return result


def _json_value(value: object, *, depth: int = 0) -> JsonValue:
    if depth > 12:
        raise ProtocolError("JSON payload is too deeply nested")
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, list):
        unknown_list = cast(list[object], value)
        return [_json_value(item, depth=depth + 1) for item in unknown_list]
    if isinstance(value, dict):
        result: dict[str, object] = {}
        unknown = cast(dict[object, object], value)
        for key, item in unknown.items():
            if not isinstance(key, str):
                raise ProtocolError("JSON object keys must be strings")
            result[key] = _json_value(item, depth=depth + 1)
        return result
    raise ProtocolError(f"unsupported JSON value {type(value).__name__}")


def json_object(value: object, label: str) -> dict[str, object]:
    parsed = _json_value(value)
    mapping = object_mapping(parsed, label)
    if len(json.dumps(mapping, ensure_ascii=False)) > 65_536:
        raise ProtocolError(f"{label} is too large")
    return mapping


@final
@dataclass(frozen=True)
class ClientContext:
    surface: str
    view_id: str

    @classmethod
    def parse(cls, raw: object) -> ClientContext:
        mapping = object_mapping(raw, "client_context")
        _strict_keys(mapping, {"surface", "view_id"}, "client_context")
        surface = mapping["surface"]
        if surface not in {"terminal", "web", "vscode", "test", "macos"}:
            raise ProtocolError("unsupported client surface")
        return cls(
            surface=str(surface),
            view_id=valid_identifier(mapping["view_id"], "view_id"),
        )

    def to_json(self) -> dict[str, object]:
        return {"surface": self.surface, "view_id": self.view_id}


@final
@dataclass(frozen=True)
class WorkspaceCommand:
    protocol_version: int
    command_id: str
    expected_cursor: int
    type: str
    payload: dict[str, object]
    client_context: ClientContext

    @classmethod
    def parse(cls, raw: object) -> WorkspaceCommand:
        mapping = object_mapping(raw, "command")
        _strict_keys(
            mapping,
            {
                "protocol_version",
                "command_id",
                "expected_cursor",
                "type",
                "payload",
                "client_context",
            },
            "command",
        )
        version = mapping["protocol_version"]
        if isinstance(version, bool) or version != PROTOCOL_VERSION:
            raise ProtocolError("unsupported protocol_version")
        cursor = mapping["expected_cursor"]
        if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
            raise ProtocolError("expected_cursor must be a non-negative integer")
        command_type = mapping["type"]
        if not isinstance(command_type, str) or command_type not in _COMMAND_TYPES:
            raise ProtocolError("unsupported command type")
        return cls(
            protocol_version=PROTOCOL_VERSION,
            command_id=valid_identifier(mapping["command_id"], "command_id"),
            expected_cursor=cursor,
            type=command_type,
            payload=json_object(mapping["payload"], "payload"),
            client_context=ClientContext.parse(mapping["client_context"]),
        )

    def fingerprint(self) -> str:
        canonical = json.dumps(
            {"type": self.type, "payload": self.payload},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
