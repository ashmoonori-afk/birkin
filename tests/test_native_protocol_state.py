from __future__ import annotations

import pytest

from birkin.native.protocol import NativeEnvelope, NativeProtocolError
from birkin.native.state import MAX_TRACKED_FRAME_IDS, NativeConnectionState
from tests.native_protocol_support import (
    hello,
    message,
    ready,
    subscribed_state,
)


def _exchange_heartbeat(state: NativeConnectionState, index: int) -> None:
    """Drive one client ping and its correlated server pong."""
    frame_id = f"heartbeat-ping-{index}"
    state.receive(
        message(
            "ping",
            frame_id=frame_id,
            body={
                "session_capability": "opaque",
                "sent_at": "2026-08-17T00:00:00Z",
            },
        )
    )
    state.send(
        message(
            "pong",
            frame_id=f"heartbeat-pong-{index}",
            in_reply_to=frame_id,
            body={"sent_at": "2026-08-17T00:00:00Z"},
        )
    )


def test_server_connection_accepts_correlated_handshake() -> None:
    state = NativeConnectionState.server()

    state.receive(hello())
    state.send(ready())

    assert state.phase == "ready"


def test_server_rejects_server_originated_kind_from_client() -> None:
    state = NativeConnectionState.server()

    with pytest.raises(NativeProtocolError) as exc_info:
        state.receive(ready())

    assert exc_info.value.code == "E_DIRECTION"


def test_server_rejects_subscribe_before_handshake() -> None:
    state = NativeConnectionState.server()
    subscribe = message(
        "subscribe",
        frame_id="subscribe-1",
        body={
            "session_id": "session-1",
            "after_cursor": 0,
            "known_instance_id": None,
            "session_capability": "opaque",
            "surfaces": {},
        },
    )

    with pytest.raises(NativeProtocolError) as exc_info:
        state.receive(subscribe)

    assert exc_info.value.code == "E_STATE"


def test_connection_rejects_duplicate_frame_identifier() -> None:
    state = NativeConnectionState.server()
    hello_frame = hello()
    state.receive(hello_frame)

    with pytest.raises(NativeProtocolError) as exc_info:
        state.receive(hello_frame)

    assert exc_info.value.code == "E_DUPLICATE_FRAME_ID"


def test_long_lived_stream_survives_more_frames_than_the_replay_window() -> None:
    """Given a subscribed connection, When far more distinct frames than the
    replay window flow over it, Then no frame is refused."""
    state = subscribed_state()

    for index in range(5_000):
        _exchange_heartbeat(state, index)

    assert state.phase == "subscribed"


def test_recent_frame_identifier_reuse_is_still_refused() -> None:
    """Given a stream shorter than the replay window, When an already-seen
    frame id returns, Then the connection refuses it as a duplicate."""
    state = subscribed_state()
    for index in range(MAX_TRACKED_FRAME_IDS // 2):
        _exchange_heartbeat(state, index)

    with pytest.raises(NativeProtocolError) as exc_info:
        state.receive(
            message(
                "ping",
                frame_id="heartbeat-ping-0",
                body={
                    "session_capability": "opaque",
                    "sent_at": "2026-08-17T00:00:00Z",
                },
            )
        )

    assert exc_info.value.code == "E_DUPLICATE_FRAME_ID"


def test_frame_identifiers_beyond_the_replay_window_are_evicted() -> None:
    """Given more frames than the replay window, When the oldest identifier
    returns, Then it is accepted because the window no longer covers it."""
    state = subscribed_state()
    for index in range(MAX_TRACKED_FRAME_IDS):
        _exchange_heartbeat(state, index)

    state.receive(
        message(
            "ping",
            frame_id="heartbeat-ping-0",
            body={
                "session_capability": "opaque",
                "sent_at": "2026-08-17T00:00:00Z",
            },
        )
    )

    assert state.phase == "subscribed"


def test_ready_requires_correlation_to_received_hello() -> None:
    state = NativeConnectionState.server()
    state.receive(hello())

    with pytest.raises(NativeProtocolError) as exc_info:
        state.send(ready(in_reply_to="different-hello"))

    assert exc_info.value.code == "E_CORRELATION"


def test_hello_body_rejects_extra_keys() -> None:
    state = NativeConnectionState.server()
    hello_frame = hello()
    invalid = NativeEnvelope(
        protocol=hello_frame.protocol,
        protocol_version=hello_frame.protocol_version,
        kind=hello_frame.kind,
        id=hello_frame.id,
        in_reply_to=hello_frame.in_reply_to,
        body={**hello_frame.body, "extra": True},
    )

    with pytest.raises(NativeProtocolError) as exc_info:
        state.receive(invalid)

    assert exc_info.value.code == "E_BODY"


def test_command_body_rejects_extra_keys() -> None:
    state = subscribed_state()
    command = message(
        "command",
        frame_id="command-1",
        body={
            "session_capability": "opaque",
            "command": {},
            "unexpected": True,
        },
    )

    with pytest.raises(NativeProtocolError) as exc_info:
        state.receive(command)

    assert exc_info.value.code == "E_BODY"


def test_client_ping_requires_session_capability() -> None:
    state = subscribed_state()
    ping = message(
        "ping",
        frame_id="ping-1",
        body={"sent_at": "2026-08-17T00:00:00Z"},
    )

    with pytest.raises(NativeProtocolError) as exc_info:
        state.receive(ping)

    assert exc_info.value.code == "E_BODY"


def test_error_body_rejects_extra_keys_and_requires_correlation() -> None:
    state = subscribed_state()
    state.receive(
        message(
            "command",
            frame_id="command-1",
            body={"session_capability": "opaque", "command": {}},
        )
    )
    error = message(
        "error",
        frame_id="error-1",
        in_reply_to="command-1",
        body={
            "code": "E_BODY",
            "message": "bad command",
            "retryable": False,
            "unexpected": True,
        },
    )

    with pytest.raises(NativeProtocolError) as exc_info:
        state.send(error)

    assert exc_info.value.code == "E_BODY"


def test_pending_requests_are_bounded() -> None:
    state = subscribed_state()
    for index in range(64):
        state.receive(
            message(
                "ping",
                frame_id=f"ping-{index}",
                body={
                    "session_capability": "opaque",
                    "sent_at": "2026-08-17T00:00:00Z",
                },
            )
        )

    with pytest.raises(NativeProtocolError) as exc_info:
        state.receive(
            message(
                "ping",
                frame_id="ping-overflow",
                body={
                    "session_capability": "opaque",
                    "sent_at": "2026-08-17T00:00:00Z",
                },
            )
        )

    assert exc_info.value.code == "E_FLOW_VIOLATION"
