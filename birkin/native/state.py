"""Direction, schema, correlation, and phase validation for native messages."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import final

from birkin.native.protocol import (
    NativeEnvelope,
    NativeProtocolError,
)
from birkin.native.schemas import validate_body

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
_MAX_PENDING_REQUESTS = 64
_MAX_SEEN_FRAME_IDS = 1_024


@final
@dataclass(slots=True)
class NativeConnectionState:
    """One endpoint's protocol state for a single connection."""

    role: str
    phase: str = "hello_required"
    _seen_ids: set[str] = field(default_factory=set)
    _pending_received: dict[str, str] = field(default_factory=dict)
    _pending_sent: dict[str, str] = field(default_factory=dict)
    _lock: threading.RLock = field(
        default_factory=threading.RLock,
        repr=False,
    )

    @classmethod
    def server(cls) -> NativeConnectionState:
        return cls(role="server")

    @classmethod
    def client(cls) -> NativeConnectionState:
        return cls(role="client")

    def receive(self, envelope: NativeEnvelope) -> None:
        with self._lock:
            parsed = NativeEnvelope.parse(envelope.to_dict())
            self._claim_id(parsed.id)
            allowed = (
                _CLIENT_KINDS if self.role == "server" else _SERVER_KINDS
            )
            if parsed.kind not in allowed:
                raise NativeProtocolError(
                    "E_DIRECTION",
                    "message kind came from the wrong endpoint",
                )
            self._validate_phase(parsed, outbound=False)
            validate_body(
                parsed,
                client_origin=self.role == "server",
            )
            self._validate_response(parsed, self._pending_sent)
            if parsed.kind in {"hello", "command", "ping"}:
                self._ensure_pending_capacity(self._pending_received)
                self._pending_received[parsed.id] = parsed.kind
            self._advance(parsed.kind)

    def send(self, envelope: NativeEnvelope) -> None:
        with self._lock:
            parsed = NativeEnvelope.parse(envelope.to_dict())
            self._claim_id(parsed.id)
            allowed = (
                _SERVER_KINDS if self.role == "server" else _CLIENT_KINDS
            )
            if parsed.kind not in allowed:
                raise NativeProtocolError(
                    "E_DIRECTION",
                    "message kind came from the wrong endpoint",
                )
            self._validate_phase(parsed, outbound=True)
            validate_body(
                parsed,
                client_origin=self.role == "client",
            )
            self._validate_response(parsed, self._pending_received)
            if parsed.kind in {"hello", "command", "ping"}:
                self._ensure_pending_capacity(self._pending_sent)
                self._pending_sent[parsed.id] = parsed.kind
            self._advance(parsed.kind)

    def _claim_id(self, frame_id: str) -> None:
        if frame_id in self._seen_ids:
            raise NativeProtocolError(
                "E_DUPLICATE_FRAME_ID",
                "frame id was reused on this connection",
            )
        self._seen_ids.add(frame_id)
        if len(self._seen_ids) > _MAX_SEEN_FRAME_IDS:
            raise NativeProtocolError(
                "E_FLOW_VIOLATION",
                "connection retained too many frame identifiers",
            )

    @staticmethod
    def _ensure_pending_capacity(pending: dict[str, str]) -> None:
        if len(pending) >= _MAX_PENDING_REQUESTS:
            raise NativeProtocolError(
                "E_FLOW_VIOLATION",
                "connection has too many pending requests",
            )

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
