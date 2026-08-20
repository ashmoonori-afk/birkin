from __future__ import annotations

import json
import struct

import pytest

from birkin.native.protocol import (
    MAX_FRAME_BYTES,
    MAX_JSON_DEPTH,
    NATIVE_PROTOCOL_NAME,
    NATIVE_PROTOCOL_VERSION,
    NativeEnvelope,
    NativeProtocolError,
    decode_frame,
    encode_frame,
)
from birkin.workspace.contracts import PROTOCOL_VERSION


def _envelope(**overrides: object) -> dict[str, object]:
    envelope: dict[str, object] = {
        "protocol": NATIVE_PROTOCOL_NAME,
        "protocol_version": NATIVE_PROTOCOL_VERSION,
        "kind": "hello",
        "id": "frame-1",
        "in_reply_to": None,
        "body": {"client": "birkin-macos"},
    }
    envelope.update(overrides)
    return envelope


def _nested_body(levels: int) -> dict[str, object]:
    root: dict[str, object] = {}
    current = root
    for _ in range(levels):
        child: dict[str, object] = {}
        current["child"] = child
        current = child
    return root


def test_native_frame_round_trips_strict_envelope() -> None:
    frame = encode_frame(_envelope())

    assert frame[:4] == struct.pack(">I", len(frame) - 4)
    assert decode_frame(frame) == NativeEnvelope(
        protocol=NATIVE_PROTOCOL_NAME,
        protocol_version=NATIVE_PROTOCOL_VERSION,
        kind="hello",
        id="frame-1",
        in_reply_to=None,
        body={"client": "birkin-macos"},
    )


def test_native_version_is_independent_from_workspace_command_version() -> None:
    nested_command = {
        "protocol_version": PROTOCOL_VERSION + 1,
        "command_id": "future-workspace-command",
    }

    envelope = decode_frame(
        encode_frame(_envelope(kind="command", body={"command": nested_command}))
    )

    assert envelope.protocol_version == NATIVE_PROTOCOL_VERSION
    assert envelope.body["command"] == nested_command


def test_future_native_version_offer_remains_parseable_in_hello() -> None:
    envelope = decode_frame(
        encode_frame(
            _envelope(
                body={
                    "client": "birkin-macos",
                    "supported_protocol_versions": [NATIVE_PROTOCOL_VERSION + 1],
                }
            )
        )
    )

    assert envelope.body["supported_protocol_versions"] == [
        NATIVE_PROTOCOL_VERSION + 1
    ]


def test_native_envelope_accepts_json_at_maximum_depth() -> None:
    envelope = _envelope(body=_nested_body(MAX_JSON_DEPTH - 1))

    assert decode_frame(encode_frame(envelope)).body == envelope["body"]


def test_native_envelope_rejects_json_beyond_maximum_depth() -> None:
    envelope = _envelope(body=_nested_body(MAX_JSON_DEPTH))

    with pytest.raises(NativeProtocolError) as exc_info:
        _ = encode_frame(envelope)

    assert exc_info.value.code == "E_JSON_DEPTH"


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


def test_native_frame_rejects_duplicate_json_keys() -> None:
    text = (
        '{"protocol":"birkin-local-1","protocol_version":1,'
        '"kind":"ping","kind":"pong","id":"duplicate-key",'
        '"in_reply_to":null,"body":{}}'
    )
    body = text.encode()

    with pytest.raises(NativeProtocolError) as exc_info:
        _ = decode_frame(struct.pack(">I", len(body)) + body)

    assert exc_info.value.code == "E_DUPLICATE_KEY"


@pytest.mark.parametrize("constant", ("NaN", "Infinity", "-Infinity"))
def test_native_frame_rejects_nonfinite_json_numbers(constant: str) -> None:
    text = (
        '{"protocol":"birkin-local-1","protocol_version":1,'
        '"kind":"ping","id":"nonfinite","in_reply_to":null,'
        f'"body":{{"value":{constant}}}}}'
    )
    body = text.encode()

    with pytest.raises(NativeProtocolError) as exc_info:
        _ = decode_frame(struct.pack(">I", len(body)) + body)

    assert exc_info.value.code == "E_NONFINITE_NUMBER"


def test_native_frame_rejects_unpaired_surrogate_on_ingress() -> None:
    text = (
        '{"protocol":"birkin-local-1","protocol_version":1,'
        '"kind":"ping","id":"surrogate","in_reply_to":null,'
        '"body":{"value":"\\ud800"}}'
    )
    body = text.encode()

    with pytest.raises(NativeProtocolError) as exc_info:
        _ = decode_frame(struct.pack(">I", len(body)) + body)

    assert exc_info.value.code == "E_JSON"


def test_native_frame_rejects_integer_outside_int64_on_ingress() -> None:
    text = (
        '{"protocol":"birkin-local-1","protocol_version":1,'
        '"kind":"ping","id":"wide-integer","in_reply_to":null,'
        f'"body":{{"value":{2**70}}}}}'
    )
    body = text.encode()

    with pytest.raises(NativeProtocolError) as exc_info:
        _ = decode_frame(struct.pack(">I", len(body)) + body)

    assert exc_info.value.code == "E_JSON"


def test_native_frame_reports_invalid_unicode_during_encode_accurately() -> None:
    with pytest.raises(NativeProtocolError) as exc_info:
        _ = encode_frame(_envelope(body={"value": "\ud800"}))

    assert exc_info.value.code == "E_JSON"


def test_native_frame_rejects_nonfinite_number_during_encode() -> None:
    with pytest.raises(NativeProtocolError) as exc_info:
        _ = encode_frame(_envelope(body={"value": float("nan")}))

    assert exc_info.value.code == "E_NONFINITE_NUMBER"


def test_native_frame_revalidates_constructed_envelope() -> None:
    invalid = NativeEnvelope(
        protocol="not-birkin",
        protocol_version=NATIVE_PROTOCOL_VERSION,
        kind="ping",
        id="constructed",
        in_reply_to=None,
        body={},
    )

    with pytest.raises(NativeProtocolError) as exc_info:
        _ = encode_frame(invalid)

    assert exc_info.value.code == "E_PROTOCOL"


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
