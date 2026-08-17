from __future__ import annotations

import pytest

from birkin.native.protocol import (
    NATIVE_PROTOCOL_NAME,
    NATIVE_PROTOCOL_VERSION,
    NativeEnvelope,
    NativeProtocolError,
)
from birkin.native.state import NativeConnectionState


def _message(
    kind: str,
    *,
    frame_id: str,
    body: dict[str, object],
    in_reply_to: str | None = None,
) -> NativeEnvelope:
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


def _hello(*, frame_id: str = "hello-1") -> NativeEnvelope:
    return _message(
        "hello",
        frame_id=frame_id,
        body={
            "client": "birkin-macos",
            "client_version": "1.0.0",
            "client_build": "100",
            "supported_protocol_versions": [NATIVE_PROTOCOL_VERSION],
            "surface": "macos",
            "view_id": "window-main",
            "bootstrap_secret": None,
        },
    )


def _ready(*, in_reply_to: str = "hello-1") -> NativeEnvelope:
    return _message(
        "ready",
        frame_id="ready-1",
        in_reply_to=in_reply_to,
        body={
            "protocol_version": NATIVE_PROTOCOL_VERSION,
            "server_version": "1.0.0",
            "instance_id": "instance-1",
            "transport": "uds",
            "capability": {"token": "opaque"},
            "limits": {},
            "capabilities": {},
        },
    )


def test_server_connection_accepts_correlated_handshake() -> None:
    state = NativeConnectionState.server()

    state.receive(_hello())
    state.send(_ready())

    assert state.phase == "ready"


def test_server_rejects_server_originated_kind_from_client() -> None:
    state = NativeConnectionState.server()

    with pytest.raises(NativeProtocolError) as exc_info:
        state.receive(_ready())

    assert exc_info.value.code == "E_DIRECTION"


def test_server_rejects_subscribe_before_handshake() -> None:
    state = NativeConnectionState.server()
    subscribe = _message(
        "subscribe",
        frame_id="subscribe-1",
        body={
            "session_id": "session-1",
            "after_cursor": 0,
            "session_capability": "opaque",
            "surfaces": {},
        },
    )

    with pytest.raises(NativeProtocolError) as exc_info:
        state.receive(subscribe)

    assert exc_info.value.code == "E_STATE"


def test_connection_rejects_duplicate_frame_identifier() -> None:
    state = NativeConnectionState.server()
    hello = _hello()
    state.receive(hello)

    with pytest.raises(NativeProtocolError) as exc_info:
        state.receive(hello)

    assert exc_info.value.code == "E_DUPLICATE_FRAME_ID"


def test_ready_requires_correlation_to_received_hello() -> None:
    state = NativeConnectionState.server()
    state.receive(_hello())

    with pytest.raises(NativeProtocolError) as exc_info:
        state.send(_ready(in_reply_to="different-hello"))

    assert exc_info.value.code == "E_CORRELATION"


def test_hello_body_rejects_extra_keys() -> None:
    state = NativeConnectionState.server()
    hello = _hello()
    invalid = NativeEnvelope(
        protocol=hello.protocol,
        protocol_version=hello.protocol_version,
        kind=hello.kind,
        id=hello.id,
        in_reply_to=hello.in_reply_to,
        body={**hello.body, "extra": True},
    )

    with pytest.raises(NativeProtocolError) as exc_info:
        state.receive(invalid)

    assert exc_info.value.code == "E_BODY"
