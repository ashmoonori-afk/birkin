"""Native bridge message construction and bounded body parsing."""

from __future__ import annotations

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
                    "max_json_depth": MAX_JSON_DEPTH,
                },
                "capabilities": {
                    "commands": sorted(self._command_types),
                },
            },
        )

    def error(self, error: NativeProtocolError) -> NativeEnvelope:
        return self.message(
            "error",
            body={
                "code": error.code,
                "message": str(error)[:300],
                "retryable": False,
            },
        )

    def message(
        self,
        kind: str,
        *,
        body: dict[str, object],
        in_reply_to: str | None = None,
    ) -> NativeEnvelope:
        self._next_id += 1
        return NativeEnvelope.parse(
            {
                "protocol": NATIVE_PROTOCOL_NAME,
                "protocol_version": NATIVE_PROTOCOL_VERSION,
                "kind": kind,
                "id": f"server-{self._next_id}",
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
