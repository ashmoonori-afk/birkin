from __future__ import annotations

from birkin.native.protocol import (
    NATIVE_PROTOCOL_NAME,
    NATIVE_PROTOCOL_VERSION,
    NativeEnvelope,
)
from birkin.native.state import NativeConnectionState


def message(
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


def hello(*, frame_id: str = "hello-1") -> NativeEnvelope:
    return message(
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


def ready(*, in_reply_to: str = "hello-1") -> NativeEnvelope:
    return message(
        "ready",
        frame_id="ready-1",
        in_reply_to=in_reply_to,
        body={
            "protocol_version": NATIVE_PROTOCOL_VERSION,
            "server_version": "1.0.0",
            "instance_id": "instance-1",
            "transport": "uds",
            "capability": {
                "token": "opaque",
                "expires_at": "2026-08-17T00:15:00+00:00",
                "hard_expires_at": "2026-08-17T08:00:00+00:00",
            },
            "limits": {
                "max_frame_bytes": 262_144,
                "max_payload_bytes": 65_536,
                "max_json_depth": 12,
                "max_inflight_commands": 8,
                "max_subscriptions": 32,
            },
            "capabilities": {
                "commands": ["chat.send"],
                "panels": [],
                "features": {},
            },
        },
    )


def subscribed_state() -> NativeConnectionState:
    state = NativeConnectionState.server()
    state.receive(hello())
    state.send(ready())
    state.receive(
        message(
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
    )
    return state
