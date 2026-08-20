"""Strict framing and envelopes for Birkin's local native protocol."""

from __future__ import annotations

import json
import math
import re
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from typing import NoReturn, TypeAlias, cast

NATIVE_PROTOCOL_NAME = "birkin-local-1"
NATIVE_PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 262_144
MAX_JSON_DEPTH = 12

JSONValue: TypeAlias = (
    None
    | bool
    | int
    | float
    | str
    | list["JSONValue"]
    | dict[str, "JSONValue"]
)

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
_IDENTIFIER = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class NativeProtocolError(ValueError):
    """A bounded protocol refusal with a stable public code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code: str = code


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
    except json.JSONDecodeError as exc:
        raise NativeProtocolError("E_JSON", "frame body is not valid JSON") from exc
    return NativeEnvelope.parse(raw)


def _object_mapping(raw: object, label: str) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise NativeProtocolError("E_JSON", f"{label} must be a JSON object")
    mapping = cast(dict[object, object], raw)
    if not all(isinstance(key, str) for key in mapping):
        raise NativeProtocolError("E_JSON", f"{label} must be a JSON object")
    return cast(dict[str, object], mapping)


def _identifier(raw: object, label: str) -> str:
    if not isinstance(raw, str) or _IDENTIFIER.fullmatch(raw) is None:
        raise NativeProtocolError(
            "E_IDENTIFIER",
            f"{label} must be a bounded identifier",
        )
    return raw


def _json_object(raw: object, *, depth: int) -> dict[str, JSONValue]:
    if not isinstance(raw, dict):
        raise NativeProtocolError("E_JSON", "body must be a JSON object")
    mapping = cast(dict[object, object], raw)
    if not all(isinstance(key, str) for key in mapping):
        raise NativeProtocolError("E_JSON", "body must be a JSON object")
    if depth > MAX_JSON_DEPTH:
        raise NativeProtocolError("E_JSON_DEPTH", "JSON exceeds maximum depth")
    return {
        cast(str, key): _json_value(value, depth=depth + 1)
        for key, value in mapping.items()
    }


def _json_value(raw: object, *, depth: int) -> JSONValue:
    if depth > MAX_JSON_DEPTH:
        raise NativeProtocolError("E_JSON_DEPTH", "JSON exceeds maximum depth")
    if isinstance(raw, float) and not math.isfinite(raw):
        raise NativeProtocolError(
            "E_NONFINITE_NUMBER",
            "body contains a non-finite number",
        )
    if raw is None or isinstance(raw, bool | int | float | str):
        return raw
    if isinstance(raw, list):
        values = cast(list[object], raw)
        return [_json_value(value, depth=depth + 1) for value in values]
    if isinstance(raw, dict):
        return _json_object(cast(object, raw), depth=depth)
    raise NativeProtocolError("E_JSON", "body contains a non-JSON value")


def _strict_object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    mapping: dict[str, object] = {}
    for key, value in pairs:
        if key in mapping:
            raise NativeProtocolError(
                "E_DUPLICATE_KEY",
                "JSON object contains a duplicate key",
            )
        mapping[key] = value
    return mapping


def _reject_nonfinite(_value: str) -> NoReturn:
    raise NativeProtocolError(
        "E_NONFINITE_NUMBER",
        "JSON contains a non-finite number",
    )
