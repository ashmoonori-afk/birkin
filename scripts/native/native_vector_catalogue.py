"""The catalogue of native-protocol envelopes exported as golden vectors.

Every registered kind in ``birkin.native.protocol`` appears here, plus the wire
edges a second implementation is most likely to get wrong: non-ASCII text and
escapes, float and integer formatting, the maximum body depth, key ordering,
and identifiers at their bound.
"""

from __future__ import annotations

from birkin import __version__
from birkin.native.protocol import (
    MAX_FRAME_BYTES,
    MAX_JSON_DEPTH,
    NATIVE_PROTOCOL_NAME,
    NATIVE_PROTOCOL_VERSION,
)


def envelope(
    kind: str,
    frame_id: str,
    body: dict[str, object],
    in_reply_to: str | None = None,
) -> dict[str, object]:
    """One envelope in the exact key order the Python codec serialises."""

    return {
        "protocol": NATIVE_PROTOCOL_NAME,
        "protocol_version": NATIVE_PROTOCOL_VERSION,
        "kind": kind,
        "id": frame_id,
        "in_reply_to": in_reply_to,
        "body": body,
    }


def _nested_body(levels: int) -> dict[str, object]:
    body: dict[str, object] = {"leaf": "bottom"}
    for _ in range(levels):
        body = {"child": body}
    return body


def _control_characters() -> str:
    return "".join(chr(code) for code in range(0x20))


def build_vectors() -> list[tuple[str, dict[str, object]]]:
    """Return every named vector, one per registered kind plus wire edges."""

    return [
        (
            "hello",
            envelope(
                "hello",
                "hello-1",
                {
                    "client": "birkin-macos",
                    "client_version": "0.1.0",
                    "supported_protocol_versions": [NATIVE_PROTOCOL_VERSION],
                },
            ),
        ),
        (
            "ready",
            envelope(
                "ready",
                "ready-1",
                {
                    "protocol_version": NATIVE_PROTOCOL_VERSION,
                    "server_version": __version__,
                    "instance_id": "birkin-local",
                    "session_id": "session-1",
                    "transport": "uds",
                    "capability": {
                        "token": "cap-token-1",
                        "expires_at": "2026-08-20T12:00:00+00:00",
                        "hard_expires_at": "2026-08-20T18:00:00+00:00",
                    },
                    "limits": {
                        "max_frame_bytes": MAX_FRAME_BYTES,
                        "max_json_depth": MAX_JSON_DEPTH,
                        "max_inflight_commands": 8,
                        "max_subscriptions": 16,
                    },
                    "capabilities": {
                        "commands": ["session.select", "conversation.send"],
                        "panels": ["session", "conversation", "terminal"],
                        "features": {},
                    },
                },
                in_reply_to="hello-1",
            ),
        ),
        (
            "subscribe",
            envelope(
                "subscribe",
                "subscribe-1",
                {"surfaces": ["session", "conversation"], "cursor": 0, "replay": True},
            ),
        ),
        (
            "snapshot",
            envelope(
                "snapshot",
                "snapshot-1",
                {
                    "surface": "session",
                    "cursor": 42,
                    "records": [
                        {"id": "s-1", "title": "Session one", "active": True},
                        {"id": "s-2", "title": "Session two", "active": False},
                    ],
                },
                in_reply_to="subscribe-1",
            ),
        ),
        (
            "event",
            envelope(
                "event",
                "event-1",
                {
                    "surface": "conversation",
                    "cursor": 43,
                    "delta": {
                        "op": "append",
                        "record": {"id": "m-9", "role": "assistant", "text": "done"},
                    },
                },
            ),
        ),
        (
            "surface_snapshot",
            envelope(
                "surface_snapshot",
                "surface-snapshot-1",
                {
                    "surface": "terminal",
                    "cursor": 7,
                    "state": {"rows": 24, "columns": 80, "lines": ["$ birkin status"]},
                },
            ),
        ),
        (
            "surface_event",
            envelope(
                "surface_event",
                "surface-event-1",
                {
                    "surface": "terminal",
                    "cursor": 8,
                    "patch": {"op": "line", "index": 0, "text": "$ birkin run"},
                },
            ),
        ),
        (
            "command",
            envelope(
                "command",
                "command-1",
                {
                    "command": {
                        "protocol_version": 1,
                        "command_id": "cmd-1",
                        "type": "session.select",
                        "params": {"session_id": "s-1"},
                    }
                },
            ),
        ),
        (
            "receipt",
            envelope(
                "receipt",
                "receipt-1",
                {"command_id": "cmd-1", "status": "accepted", "cursor": 44},
                in_reply_to="command-1",
            ),
        ),
        (
            "error",
            envelope(
                "error",
                "error-1",
                {
                    "code": "E_UNSUPPORTED_COMMAND",
                    "message": "unsupported command",
                    "retryable": False,
                },
                in_reply_to="command-1",
            ),
        ),
        (
            "capability_renewed",
            envelope(
                "capability.renewed",
                "capability-1",
                {
                    "token": "cap-token-2",
                    "expires_at": "2026-08-20T13:00:00+00:00",
                    "hard_expires_at": "2026-08-20T18:00:00+00:00",
                },
            ),
        ),
        (
            "stream_desynchronized",
            envelope(
                "stream.desynchronized",
                "desync-1",
                {
                    "surface": "conversation",
                    "expected_cursor": 44,
                    "received_cursor": 51,
                    "action": "resubscribe",
                },
            ),
        ),
        ("ping", envelope("ping", "ping-1", {"nonce": "n-1"})),
        ("pong", envelope("pong", "pong-1", {"nonce": "n-1"}, in_reply_to="ping-1")),
        ("goodbye", envelope("goodbye", "goodbye-1", {"reason": "client_exit"})),
        ("empty_body", envelope("ping", "empty-1", {})),
        (
            "unicode_and_escapes",
            envelope(
                "event",
                "unicode-1",
                {
                    "korean": "안녕하세요 버킨",
                    "emoji": "🛰️ 작업 완료",
                    "quotes": 'he said "hi" and left',
                    "backslashes": "C:\\\\Users\\birkin",
                    "whitespace": "tab\there\nnewline\r\n",
                    "controls": _control_characters(),
                    "delete_and_separators": "\x7f\u2028\u2029",
                    "solidus": "a/b",
                },
            ),
        ),
        (
            "numeric_edges",
            envelope(
                "event",
                "numeric-1",
                {
                    "zero": 0,
                    "negative": -1,
                    "large_int": 9007199254740993,
                    "int64_min": -9223372036854775808,
                    "one_point_zero": 1.0,
                    "negative_zero": -0.0,
                    "tenth": 0.1,
                    "third": 1 / 3,
                    "fixed_upper": 1e15,
                    "exponent_upper": 1e16,
                    "fixed_lower": 1e-4,
                    "exponent_lower": 1e-5,
                    "max_double": 1.7976931348623157e308,
                    "min_subnormal": 5e-324,
                    "mixed": [1, 1.5, -2.25, 1e100],
                },
            ),
        ),
        (
            "maximum_depth",
            envelope(
                "command",
                "depth-1",
                _nested_body(MAX_JSON_DEPTH - 2),
            ),
        ),
        (
            "key_order",
            envelope(
                "snapshot",
                "order-1",
                {"zulu": 1, "alpha": 2, "mike": 3, "bravo": {"zeta": 1, "alpha": 2}},
            ),
        ),
        (
            "bounded_identifiers",
            envelope(
                "receipt",
                "i" * 128,
                {"command_id": "a.b:c-d_e", "status": "accepted"},
                in_reply_to="a.b:c-d_e",
            ),
        ),
    ]
