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
CONTROL_COMMAND_TYPES = frozenset({
    "chat.interrupt",
    "chat.resume",
    "chat.steer",
})

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
    "browser.back",
    "browser.forward",
    "browser.reload",
    "browser.close",
    "computer.answer",
    "computer.execute",
    "office.create",
    "office.select",
    "office.open",
    "office.convert",
    "office.compare",
    "office.job_request",
    "file.import",
    "skill.reload",
    "checkpoint.restore",
    "config.set",
    "gateway.restart",
}

JsonValue = object

# Written wherever a public projection must not carry a secret. It is proof a
# value was withheld, never a usable value.
REDACTION_MARKER = "[REDACTED]"


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


class TerminalUnsupported(ProtocolError):
    """This platform cannot provide the requested terminal capability."""

    capability: str

    def __init__(self, capability: str, reason: str) -> None:
        super().__init__(f"{capability} capability is unavailable: {reason}")
        self.capability = capability


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
class ChatAttachment:
    """A canonical reference to a file copied into this session's import jail."""

    import_id: str
    display_name: str
    jail_name: str
    sha256: str
    byte_count: int

    @classmethod
    def parse(cls, raw: object) -> ChatAttachment:
        mapping = object_mapping(raw, "chat attachment")
        _strict_keys(
            mapping,
            {"kind", "import_id", "display_name", "jail_name", "sha256", "byte_count"},
            "chat attachment",
        )
        if mapping["kind"] != "workspace_import":
            raise ProtocolError("chat attachment kind must be workspace_import")
        import_id = valid_identifier(mapping["import_id"], "attachment import_id")
        display_name = mapping["display_name"]
        jail_name = mapping["jail_name"]
        digest = mapping["sha256"]
        byte_count = mapping["byte_count"]
        if not isinstance(display_name, str) or not display_name or len(display_name) > 255:
            raise ProtocolError("attachment display_name must be non-empty")
        if not isinstance(jail_name, str) or _JAIL_NAME.fullmatch(jail_name) is None:
            raise ProtocolError("attachment jail_name is invalid")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ProtocolError("attachment sha256 is invalid")
        if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count < 0:
            raise ProtocolError("attachment byte_count must be a non-negative integer")
        return cls(import_id, display_name, jail_name, digest, byte_count)

    def to_json(self) -> dict[str, object]:
        return {
            "kind": "workspace_import",
            "import_id": self.import_id,
            "display_name": self.display_name,
            "jail_name": self.jail_name,
            "sha256": self.sha256,
            "byte_count": self.byte_count,
        }


_JAIL_NAME = re.compile(r"[A-Za-z0-9._-]{1,255}")


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
        if surface not in {"terminal", "web", "vscode", "test", "macos", "windows"}:
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
