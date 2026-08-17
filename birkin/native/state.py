"""Direction, schema, correlation, and phase validation for native messages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import final

from birkin.native.protocol import (
    NATIVE_PROTOCOL_VERSION,
    JSONValue,
    NativeEnvelope,
    NativeProtocolError,
)

_CLIENT_KINDS = {
    "hello",
    "subscribe",
    "command",
    "ping",
    "pong",
    "goodbye",
}
_SERVER_KINDS = {
    "ready",
    "snapshot",
    "event",
    "surface_snapshot",
    "surface_event",
    "receipt",
    "error",
    "capability.renewed",
    "stream.desynchronized",
    "ping",
    "pong",
    "goodbye",
}
_HELLO_KEYS = {
    "client",
    "client_version",
    "client_build",
    "supported_protocol_versions",
    "surface",
    "view_id",
    "bootstrap_secret",
}
_READY_KEYS = {
    "protocol_version",
    "server_version",
    "instance_id",
    "transport",
    "capability",
    "limits",
    "capabilities",
}
_SUBSCRIBE_KEYS = {
    "session_id",
    "after_cursor",
    "session_capability",
    "surfaces",
}


@final
@dataclass(slots=True)
class NativeConnectionState:
    """One endpoint's protocol state for a single connection."""

    role: str
    phase: str = "hello_required"
    _seen_ids: set[str] = field(default_factory=set)
    _pending_received: dict[str, str] = field(default_factory=dict)
    _pending_sent: dict[str, str] = field(default_factory=dict)

    @classmethod
    def server(cls) -> NativeConnectionState:
        return cls(role="server")

    @classmethod
    def client(cls) -> NativeConnectionState:
        return cls(role="client")

    def receive(self, envelope: NativeEnvelope) -> None:
        parsed = NativeEnvelope.parse(envelope.to_dict())
        self._claim_id(parsed.id)
        allowed = _CLIENT_KINDS if self.role == "server" else _SERVER_KINDS
        if parsed.kind not in allowed:
            raise NativeProtocolError(
                "E_DIRECTION",
                "message kind came from the wrong endpoint",
            )
        self._validate_phase(parsed, outbound=False)
        _validate_body(parsed)
        self._validate_response(parsed, self._pending_sent)
        if parsed.kind in {"hello", "command", "ping"}:
            self._pending_received[parsed.id] = parsed.kind
        self._advance(parsed.kind)

    def send(self, envelope: NativeEnvelope) -> None:
        parsed = NativeEnvelope.parse(envelope.to_dict())
        self._claim_id(parsed.id)
        allowed = _SERVER_KINDS if self.role == "server" else _CLIENT_KINDS
        if parsed.kind not in allowed:
            raise NativeProtocolError(
                "E_DIRECTION",
                "message kind came from the wrong endpoint",
            )
        self._validate_phase(parsed, outbound=True)
        _validate_body(parsed)
        self._validate_response(parsed, self._pending_received)
        if parsed.kind in {"hello", "command", "ping"}:
            self._pending_sent[parsed.id] = parsed.kind
        self._advance(parsed.kind)

    def _claim_id(self, frame_id: str) -> None:
        if frame_id in self._seen_ids:
            raise NativeProtocolError(
                "E_DUPLICATE_FRAME_ID",
                "frame id was reused on this connection",
            )
        self._seen_ids.add(frame_id)

    def _validate_phase(self, envelope: NativeEnvelope, *, outbound: bool) -> None:
        if self.phase == "hello_required":
            expected = (
                self.role == "server"
                and not outbound
                or self.role == "client"
                and outbound
            )
            if envelope.kind != "hello" or not expected:
                raise NativeProtocolError(
                    "E_STATE",
                    "hello is required before negotiation",
                )
            return
        if self.phase == "negotiated":
            expected = (
                self.role == "server"
                and outbound
                or self.role == "client"
                and not outbound
            )
            if envelope.kind != "ready" or not expected:
                raise NativeProtocolError(
                    "E_STATE",
                    "ready is required after hello",
                )
            return
        if self.phase == "ready" and envelope.kind not in {
            "subscribe",
            "ping",
            "pong",
            "goodbye",
        }:
            raise NativeProtocolError(
                "E_STATE",
                "subscribe is required before session messages",
            )
        if self.phase == "closed":
            raise NativeProtocolError("E_STATE", "connection is closed")

    def _validate_response(
        self,
        envelope: NativeEnvelope,
        pending: dict[str, str],
    ) -> None:
        expected_request = {
            "ready": "hello",
            "receipt": "command",
            "error": None,
            "pong": "ping",
        }.get(envelope.kind)
        if expected_request is None and envelope.kind != "error":
            if envelope.in_reply_to is not None:
                raise NativeProtocolError(
                    "E_CORRELATION",
                    "unsolicited message cannot carry in_reply_to",
                )
            return
        reply = envelope.in_reply_to
        if reply is None or reply not in pending:
            raise NativeProtocolError(
                "E_CORRELATION",
                "response does not match a pending request",
            )
        if expected_request is not None and pending[reply] != expected_request:
            raise NativeProtocolError(
                "E_CORRELATION",
                "response kind does not match its request",
            )
        del pending[reply]

    def _advance(self, kind: str) -> None:
        if kind == "hello":
            self.phase = "negotiated"
        elif kind == "ready":
            self.phase = "ready"
        elif kind == "subscribe":
            self.phase = "subscribed"
        elif kind == "goodbye":
            self.phase = "closed"


def _validate_body(envelope: NativeEnvelope) -> None:
    if envelope.kind == "hello":
        _validate_hello(envelope.body)
    elif envelope.kind == "ready":
        _exact_keys(envelope.body, _READY_KEYS)
        version = envelope.body["protocol_version"]
        if version != NATIVE_PROTOCOL_VERSION:
            raise NativeProtocolError(
                "E_PROTOCOL_VERSION",
                "ready selected an unsupported native protocol version",
            )
    elif envelope.kind == "subscribe":
        _exact_keys(envelope.body, _SUBSCRIBE_KEYS)
        cursor = envelope.body["after_cursor"]
        if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
            raise NativeProtocolError(
                "E_BODY",
                "after_cursor must be a non-negative integer",
            )


def _validate_hello(body: dict[str, JSONValue]) -> None:
    _exact_keys(body, _HELLO_KEYS)
    for key in ("client", "client_version", "client_build", "surface", "view_id"):
        if not isinstance(body[key], str):
            raise NativeProtocolError("E_BODY", f"{key} must be a string")
    versions = body["supported_protocol_versions"]
    if (
        not isinstance(versions, list)
        or not versions
        or any(isinstance(value, bool) or not isinstance(value, int) for value in versions)
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


def _exact_keys(body: dict[str, JSONValue], expected: set[str]) -> None:
    if set(body) != expected:
        raise NativeProtocolError(
            "E_BODY",
            "message body keys do not match the kind schema",
        )
