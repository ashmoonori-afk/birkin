"""Strict framing and envelopes for Birkin's local native protocol."""

from __future__ import annotations

import json
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from birkin.native.protocol_json import (
    JSONValue as JSONValue,
    MAX_JSON_DEPTH as MAX_JSON_DEPTH,
    NativeProtocolError as NativeProtocolError,
    identifier as _identifier,
    json_object as _json_object,
    object_mapping as _object_mapping,
    reject_nonfinite as _reject_nonfinite,
    strict_object_pairs as _strict_object_pairs,
)

NATIVE_PROTOCOL_NAME = "birkin-local-1"
NATIVE_PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 262_144

_ENVELOPE_KEYS = {
    "protocol",
    "protocol_version",
    "kind",
    "id",
    "in_reply_to",
    "body",
}
_KINDS = {
    "hello",
    "ready",
    "subscribe",
    "snapshot",
    "event",
    "surface_snapshot",
    "surface_event",
    "command",
    "receipt",
    "error",
    "capability.renewed",
    "stream.desynchronized",
    "ping",
    "pong",
    "goodbye",
}

__all__ = [
    "JSONValue",
    "MAX_FRAME_BYTES",
    "MAX_JSON_DEPTH",
    "NATIVE_PROTOCOL_NAME",
    "NATIVE_PROTOCOL_VERSION",
    "NativeEnvelope",
    "NativeProtocolError",
    "decode_frame",
    "encode_frame",
]


@dataclass(frozen=True, slots=True)
class NativeEnvelope:
    """One validated native-protocol envelope."""

    protocol: str
    protocol_version: int
    kind: str
    id: str
    in_reply_to: str | None
    body: dict[str, JSONValue]

    @classmethod
    def parse(cls, raw: object) -> NativeEnvelope:
        mapping = _object_mapping(raw, "envelope")
        if set(mapping) != _ENVELOPE_KEYS:
            raise NativeProtocolError(
                "E_ENVELOPE_KEYS",
                "native envelope keys do not match the protocol",
            )
        protocol = mapping["protocol"]
        if not isinstance(protocol, str) or protocol != NATIVE_PROTOCOL_NAME:
            raise NativeProtocolError("E_PROTOCOL", "unsupported native protocol")
        version = mapping["protocol_version"]
        if isinstance(version, bool) or not isinstance(version, int):
            raise NativeProtocolError(
                "E_PROTOCOL_VERSION",
                "protocol_version must be an integer",
            )
        if version != NATIVE_PROTOCOL_VERSION:
            raise NativeProtocolError(
                "E_PROTOCOL_VERSION",
                f"unsupported protocol_version {version}",
            )
        kind = mapping["kind"]
        if not isinstance(kind, str) or kind not in _KINDS:
            raise NativeProtocolError("E_KIND", "unsupported native message kind")
        frame_id = _identifier(mapping["id"], "id")
        reply = mapping["in_reply_to"]
        if reply is not None:
            reply = _identifier(reply, "in_reply_to")
        body = _json_object(mapping["body"], depth=1)
        return cls(
            protocol=protocol,
            protocol_version=version,
            kind=kind,
            id=frame_id,
            in_reply_to=reply,
            body=body,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "protocol": self.protocol,
            "protocol_version": self.protocol_version,
            "kind": self.kind,
            "id": self.id,
            "in_reply_to": self.in_reply_to,
            "body": self.body,
        }


def encode_frame(envelope: NativeEnvelope | Mapping[str, object]) -> bytes:
    """Validate and encode one complete length-prefixed frame."""
    parsed = NativeEnvelope.parse(
        envelope.to_dict()
        if isinstance(envelope, NativeEnvelope)
        else dict(envelope)
    )
    try:
        body = json.dumps(
            parsed.to_dict(),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except UnicodeEncodeError as exc:
        raise NativeProtocolError(
            "E_JSON",
            "frame contains an invalid Unicode string",
        ) from exc
    except ValueError as exc:
        raise NativeProtocolError(
            "E_NONFINITE_NUMBER",
            "frame contains a non-finite number",
        ) from exc
    if len(body) > MAX_FRAME_BYTES:
        raise NativeProtocolError("E_FRAME_TOO_LARGE", "native frame exceeds limit")
    return struct.pack(">I", len(body)) + body


def decode_frame(frame: bytes) -> NativeEnvelope:
    """Decode one complete frame, checking the declared bound before its body."""
    if len(frame) < 4:
        raise NativeProtocolError("E_FRAME_INCOMPLETE", "frame header is incomplete")
    declared = struct.unpack(">I", frame[:4])[0]
    if declared > MAX_FRAME_BYTES:
        raise NativeProtocolError("E_FRAME_TOO_LARGE", "native frame exceeds limit")
    actual = len(frame) - 4
    if actual < declared:
        raise NativeProtocolError("E_FRAME_INCOMPLETE", "frame body is incomplete")
    if actual > declared:
        raise NativeProtocolError(
            "E_FRAME_TRAILING_DATA",
            "frame contains trailing data",
        )
    try:
        text = frame[4:].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise NativeProtocolError("E_INVALID_UTF8", "frame is not UTF-8") from exc
    try:
        raw = cast(
            object,
            json.loads(
                text,
                object_pairs_hook=_strict_object_pairs,
                parse_constant=_reject_nonfinite,
            ),
        )
    except RecursionError as exc:
        raise NativeProtocolError("E_JSON_DEPTH", "JSON exceeds maximum depth") from exc
    except NativeProtocolError:
        # Strict hooks carry a specific public refusal code through this boundary.
        raise
    except ValueError as exc:
        # Invalid syntax and interpreter integer limits are both bounded JSON refusals.
        raise NativeProtocolError("E_JSON", "frame body is not valid JSON") from exc
    return NativeEnvelope.parse(raw)
