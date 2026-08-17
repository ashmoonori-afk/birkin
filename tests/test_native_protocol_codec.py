from __future__ import annotations

import json
import struct

import pytest

from birkin.native.protocol import (
    MAX_FRAME_BYTES,
    NATIVE_PROTOCOL_NAME,
    NativeEnvelope,
    NativeProtocolError,
    decode_frame,
    encode_frame,
)
from birkin.workspace.contracts import PROTOCOL_VERSION


def _envelope(**overrides: object) -> dict[str, object]:
    envelope: dict[str, object] = {
        "protocol": NATIVE_PROTOCOL_NAME,
        "protocol_version": PROTOCOL_VERSION,
        "kind": "hello",
        "id": "frame-1",
        "in_reply_to": None,
        "body": {"client": "birkin-macos"},
    }
    envelope.update(overrides)
    return envelope


def test_native_frame_round_trips_strict_envelope() -> None:
    frame = encode_frame(_envelope())

    assert frame[:4] == struct.pack(">I", len(frame) - 4)
    assert decode_frame(frame) == NativeEnvelope(
        protocol=NATIVE_PROTOCOL_NAME,
        protocol_version=PROTOCOL_VERSION,
        kind="hello",
        id="frame-1",
        in_reply_to=None,
        body={"client": "birkin-macos"},
    )


def test_native_frame_rejects_oversized_length_before_body_read() -> None:
    declared_length = struct.pack(">I", MAX_FRAME_BYTES + 1)

    with pytest.raises(NativeProtocolError) as exc_info:
        _ = decode_frame(declared_length)

    assert exc_info.value.code == "E_FRAME_TOO_LARGE"


def test_native_frame_rejects_partial_body() -> None:
    with pytest.raises(NativeProtocolError) as exc_info:
        _ = decode_frame(struct.pack(">I", 3) + b"{}")

    assert exc_info.value.code == "E_FRAME_INCOMPLETE"


def test_native_frame_rejects_invalid_utf8() -> None:
    with pytest.raises(NativeProtocolError) as exc_info:
        _ = decode_frame(struct.pack(">I", 1) + b"\xff")

    assert exc_info.value.code == "E_INVALID_UTF8"


def test_native_envelope_rejects_extra_keys() -> None:
    payload = _envelope(extra="forbidden")
    body = json.dumps(payload, separators=(",", ":")).encode()

    with pytest.raises(NativeProtocolError) as exc_info:
        _ = decode_frame(struct.pack(">I", len(body)) + body)

    assert exc_info.value.code == "E_ENVELOPE_KEYS"


def test_native_envelope_rejects_unknown_kind() -> None:
    with pytest.raises(NativeProtocolError) as exc_info:
        _ = encode_frame(_envelope(kind="invented"))

    assert exc_info.value.code == "E_KIND"


@pytest.mark.parametrize(
    "kind",
    (
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
    ),
)
def test_native_envelope_accepts_registered_kinds(kind: str) -> None:
    assert decode_frame(encode_frame(_envelope(kind=kind))).kind == kind
