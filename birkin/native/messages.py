"""Native bridge message construction and bounded body parsing."""

from __future__ import annotations

import threading
from typing import final

from birkin.native.capability import SessionCapability
from birkin.native.protocol import (
    MAX_FRAME_BYTES,
    MAX_JSON_DEPTH,
    NATIVE_PROTOCOL_NAME,
    NATIVE_PROTOCOL_VERSION,
    JSONValue,
    NativeEnvelope,
    NativeProtocolError,
)
from birkin.native.projection import public_error_text
from birkin.workspace.contracts import (
    CommandIdConflict,
    ConfigMutationRejected,
    ProtocolError as WorkspaceProtocolError,
    StaleCursor,
    UnsupportedCommand,
)
from birkin.workspace.records import PANEL_KEYS

_MAX_PAYLOAD_BYTES = 65_536
_MAX_INFLIGHT_COMMANDS = 8
_MAX_SUBSCRIPTIONS = 32


@final
class NativeMessageFactory:
    def __init__(
        self,
        *,
        instance_id: str,
        server_version: str,
        command_types: frozenset[str],
    ) -> None:
        self._instance_id = instance_id
        self._server_version = server_version
        self._command_types = command_types
        self._next_id = 0
        self._id_lock = threading.Lock()

    def ready(
        self,
        hello: NativeEnvelope,
        capability: SessionCapability,
        *,
        transport: str,
    ) -> NativeEnvelope:
        return self.message(
            "ready",
            in_reply_to=hello.id,
            body={
                "protocol_version": NATIVE_PROTOCOL_VERSION,
                "server_version": self._server_version,
                "instance_id": self._instance_id,
                "transport": transport,
                "capability": {
                    "token": capability.token,
                    "expires_at": capability.expires_at.isoformat(),
                    "hard_expires_at": capability.hard_expires_at.isoformat(),
                },
                "limits": {
                    "max_frame_bytes": MAX_FRAME_BYTES,
                    "max_payload_bytes": _MAX_PAYLOAD_BYTES,
                    "max_json_depth": MAX_JSON_DEPTH,
                    "max_inflight_commands": _MAX_INFLIGHT_COMMANDS,
                    "max_subscriptions": _MAX_SUBSCRIPTIONS,
                },
                "capabilities": {
                    "commands": sorted(self._command_types),
                    "panels": list(PANEL_KEYS),
                    "features": {},
                },
            },
        )

    def capability_renewed(
        self,
        capability: SessionCapability,
    ) -> NativeEnvelope:
        return self.message(
            "capability.renewed",
            body={
                "token": capability.token,
                "expires_at": capability.expires_at.isoformat(),
                "hard_expires_at": capability.hard_expires_at.isoformat(),
            },
        )

    def error(
        self,
        error: NativeProtocolError,
        *,
        in_reply_to: str | None = None,
        details: dict[str, object] | None = None,
    ) -> NativeEnvelope:
        body: dict[str, object] = {
            "code": error.code,
            "message": public_error_text(str(error)),
            "retryable": False,
        }
        if details is not None:
            body.update(details)
        return self.message(
            "error",
            body=body,
            in_reply_to=in_reply_to,
        )

    def workspace_error(
        self,
        error: WorkspaceProtocolError,
        *,
        in_reply_to: str,
    ) -> NativeEnvelope:
        details: dict[str, object] | None = None
        if isinstance(error, ConfigMutationRejected):
            code = "E_CONFIG_REJECTED"
        elif isinstance(error, UnsupportedCommand):
            code = "E_UNSUPPORTED_COMMAND"
        elif isinstance(error, StaleCursor):
            code = "E_STALE_CURSOR"
            details = {"current_cursor": error.current_cursor}
        elif isinstance(error, CommandIdConflict):
            code = "E_COMMAND_ID_CONFLICT"
        else:
            code = "E_BODY"
        return self.error(
            NativeProtocolError(code, str(error)),
            in_reply_to=in_reply_to,
            details=details,
        )

    def message(
        self,
        kind: str,
        *,
        body: dict[str, object],
        in_reply_to: str | None = None,
    ) -> NativeEnvelope:
        with self._id_lock:
            self._next_id += 1
            frame_id = f"server-{self._next_id}"
        return NativeEnvelope.parse(
            {
                "protocol": NATIVE_PROTOCOL_NAME,
                "protocol_version": NATIVE_PROTOCOL_VERSION,
                "kind": kind,
                "id": frame_id,
                "in_reply_to": in_reply_to,
                "body": body,
            }
        )


def body_string(body: dict[str, JSONValue], key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str):
        raise NativeProtocolError("E_BODY", f"{key} must be a string")
    return value


def body_integer(body: dict[str, JSONValue], key: str) -> int:
    value = body.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise NativeProtocolError(
            "E_BODY",
            f"{key} must be a non-negative integer",
        )
    return value
