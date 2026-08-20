"""Exact per-kind message body schemas for the native protocol."""

from __future__ import annotations

from birkin.native.protocol import (
    NATIVE_PROTOCOL_VERSION,
    JSONValue,
    NativeEnvelope,
    NativeProtocolError,
)

_HELLO = {
    "client",
    "client_version",
    "client_build",
    "supported_protocol_versions",
    "surface",
    "view_id",
    "bootstrap_secret",
}
_READY = {
    "protocol_version",
    "server_version",
    "instance_id",
    "transport",
    "capability",
    "limits",
    "capabilities",
}
_SUBSCRIBE = {
    "session_id",
    "after_cursor",
    "known_instance_id",
    "session_capability",
    "surfaces",
}
_SNAPSHOT = {
    "protocol_version",
    "session_id",
    "cursor",
    "panels",
    "conversation",
    "composer",
    "status",
    "working_memory",
    "approval_policy",
    "terminals",
    "instance_id",
    "reset_reason",
}
_EVENT = {
    "protocol_version",
    "session_id",
    "cursor",
    "event_id",
    "type",
    "timestamp",
    "actor_id",
    "command_id",
    "payload",
}


def validate_body(
    envelope: NativeEnvelope,
    *,
    client_origin: bool,
) -> None:
    body = envelope.body
    kind = envelope.kind
    if kind == "hello":
        _validate_hello(body)
    elif kind == "ready":
        _validate_ready(body)
    elif kind == "subscribe":
        _exact(body, _SUBSCRIBE)
        _ = _non_negative_integer(body, "after_cursor")
    elif kind == "command":
        _exact(body, {"session_capability", "command"})
        _ = _string(body, "session_capability")
        _ = _mapping(body, "command")
    elif kind in {"ping", "pong"}:
        expected = (
            {"session_capability", "sent_at"}
            if client_origin
            else {"sent_at"}
        )
        _exact(body, expected)
        _ = _string(body, "sent_at")
        if client_origin:
            _ = _string(body, "session_capability")
    elif kind == "goodbye":
        expected = (
            {"session_capability", "reason"}
            if client_origin
            else {"reason"}
        )
        _exact(body, expected)
        _ = _string(body, "reason")
        if client_origin:
            _ = _string(body, "session_capability")
    elif kind == "snapshot":
        _exact(body, _SNAPSHOT)
    elif kind == "event":
        _exact(body, _EVENT)
    elif kind in {"surface_snapshot", "surface_event"}:
        _exact(body, {"surface", "revision", "payload"})
        _ = _string(body, "surface")
        _ = _non_negative_integer(body, "revision")
        _ = _mapping(body, "payload")
    elif kind == "receipt":
        required = {
            "protocol_version",
            "command_id",
            "session_id",
            "actor_id",
            "accepted_cursor",
            "state",
            "result_event_cursor",
            "duplicate",
            "outcome",
        }
        if not required.issubset(body) or not set(body).issubset(required | {"result"}):
            raise NativeProtocolError(
                "E_BODY", "message body keys do not match the kind schema"
            )
        _ = _string(body, "outcome")
        if "result" in body:
            _ = _mapping(body, "result")
    elif kind == "error":
        _error(body)
    elif kind == "capability.renewed":
        _exact(body, {"token", "expires_at", "hard_expires_at"})
        for key in ("token", "expires_at", "hard_expires_at"):
            _ = _string(body, key)
    elif kind == "stream.desynchronized":
        _exact(body, {"resume_after"})
        _ = _non_negative_integer(body, "resume_after")


def _validate_hello(body: dict[str, JSONValue]) -> None:
    _exact(body, _HELLO)
    for key in ("client", "client_version", "client_build", "surface", "view_id"):
        _ = _string(body, key)
    versions = body["supported_protocol_versions"]
    if (
        not isinstance(versions, list)
        or not versions
        or any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in versions
        )
    ):
        raise NativeProtocolError(
            "E_BODY",
            "supported_protocol_versions must contain integers",
        )
    bootstrap = body["bootstrap_secret"]
    if bootstrap is not None and not isinstance(bootstrap, str):
        raise NativeProtocolError(
            "E_BODY",
            "bootstrap_secret must be a string or null",
        )


def _validate_ready(body: dict[str, JSONValue]) -> None:
    _exact(body, _READY)
    if body["protocol_version"] != NATIVE_PROTOCOL_VERSION:
        raise NativeProtocolError(
            "E_PROTOCOL_VERSION",
            "ready selected an unsupported native protocol version",
        )
    capability = _mapping(body, "capability")
    _exact(capability, {"token", "expires_at", "hard_expires_at"})
    limits = _mapping(body, "limits")
    _exact(
        limits,
        {
            "max_frame_bytes",
            "max_payload_bytes",
            "max_json_depth",
            "max_inflight_commands",
            "max_subscriptions",
        },
    )
    capabilities = _mapping(body, "capabilities")
    _exact(capabilities, {"commands", "panels", "features"})


def _error(body: dict[str, JSONValue]) -> None:
    required = {"code", "message", "retryable"}
    allowed = required | {
        "current_cursor",
        "current_revision",
        "limit",
        "approval_id",
        "server_protocol_versions",
    }
    if not required.issubset(body) or not set(body).issubset(allowed):
        raise NativeProtocolError(
            "E_BODY",
            "message body keys do not match the kind schema",
        )
    _ = _string(body, "code")
    _ = _string(body, "message")
    if not isinstance(body["retryable"], bool):
        raise NativeProtocolError("E_BODY", "retryable must be a boolean")
    for key in ("current_cursor", "current_revision", "limit"):
        if key in body:
            _ = _non_negative_integer(body, key)
    if "approval_id" in body:
        _ = _string(body, "approval_id")


def _mapping(
    body: dict[str, JSONValue],
    key: str,
) -> dict[str, JSONValue]:
    value = body.get(key)
    if not isinstance(value, dict):
        raise NativeProtocolError("E_BODY", f"{key} must be an object")
    return value


def _string(body: dict[str, JSONValue], key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str):
        raise NativeProtocolError("E_BODY", f"{key} must be a string")
    return value


def _non_negative_integer(
    body: dict[str, JSONValue],
    key: str,
) -> int:
    value = body.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise NativeProtocolError(
            "E_BODY",
            f"{key} must be a non-negative integer",
        )
    return value


def _exact(body: dict[str, JSONValue], expected: set[str]) -> None:
    if set(body) != expected:
        raise NativeProtocolError(
            "E_BODY",
            "message body keys do not match the kind schema",
        )
