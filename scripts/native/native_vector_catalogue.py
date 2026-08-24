"""Deterministic valid and invalid vectors for the native protocol codec."""

from __future__ import annotations

import struct
from dataclasses import dataclass, replace

from birkin import __version__
from birkin.native.protocol import (
    JSONValue,
    MAX_FRAME_BYTES,
    MAX_JSON_DEPTH,
    NATIVE_PROTOCOL_NAME,
    NATIVE_PROTOCOL_VERSION,
)
from birkin.workspace.contracts import WorkspaceCommand
from birkin.workspace.records import CommandReceipt

Envelope = dict[str, JSONValue]


@dataclass(frozen=True, slots=True)
class InvalidVector:
    """One raw frame and its normative Python refusal."""

    name: str
    category: str
    frame: bytes
    expected_error_code: str


def envelope(
    kind: str,
    frame_id: str,
    body: dict[str, JSONValue],
    in_reply_to: str | None = None,
) -> Envelope:
    """Build one envelope in Python's canonical key order."""
    return {
        "protocol": NATIVE_PROTOCOL_NAME,
        "protocol_version": NATIVE_PROTOCOL_VERSION,
        "kind": kind,
        "id": frame_id,
        "in_reply_to": in_reply_to,
        "body": body,
    }


def _nested_body(levels: int) -> dict[str, JSONValue]:
    body: dict[str, JSONValue] = {"leaf": "bottom"}
    for _ in range(levels):
        body = {"child": body}
    return body


def build_vectors() -> list[tuple[str, Envelope]]:
    """Return every registered kind plus deterministic wire-format edges."""
    command = WorkspaceCommand.parse({
        "protocol_version": 1,
        "command_id": "cmd-1",
        "expected_cursor": 42,
        "type": "session.select",
        "payload": {"session_id": "s-1"},
        "client_context": {"surface": "windows", "view_id": "conversation"},
    })
    command_body = {
        "protocol_version": command.protocol_version,
        "command_id": command.command_id,
        "expected_cursor": command.expected_cursor,
        "type": command.type,
        "payload": command.payload,
        "client_context": command.client_context.to_json(),
    }
    receipt = CommandReceipt(
        protocol_version=1,
        command_id="cmd-1",
        session_id="session-1",
        actor_id="windows:conversation",
        accepted_cursor=43,
        state="completed",
        result_event_cursor=44,
        fingerprint="fixture-fingerprint",
    )
    receipt_body = receipt.to_public_json()
    receipt_body["outcome"] = "accepted"
    bounded_receipt_body = replace(
        receipt,
        command_id="a.b:c-d_e",
    ).to_public_json()
    bounded_receipt_body["outcome"] = "accepted"
    vectors: list[tuple[str, Envelope]] = [
        ("hello", envelope("hello", "hello-1", {
            "client": "birkin-macos", "client_version": "0.1.0",
            "supported_protocol_versions": [NATIVE_PROTOCOL_VERSION],
        })),
        ("ready", envelope("ready", "ready-1", {
            "protocol_version": NATIVE_PROTOCOL_VERSION,
            "server_version": __version__, "instance_id": "birkin-local",
            "session_id": "session-1", "transport": "uds",
            "capability": {
                "token": "cap-token-1", "expires_at": "2026-08-20T12:00:00+00:00",
                "hard_expires_at": "2026-08-20T18:00:00+00:00",
            },
            "limits": {
                "max_frame_bytes": MAX_FRAME_BYTES, "max_json_depth": MAX_JSON_DEPTH,
                "max_inflight_commands": 8, "max_subscriptions": 16,
            },
            "capabilities": {
                "commands": ["session.select", "conversation.send"],
                "panels": ["session", "conversation", "terminal"], "features": {},
            },
        }, "hello-1")),
        ("subscribe", envelope("subscribe", "subscribe-1", {
            "surfaces": ["session", "conversation"], "cursor": 0, "replay": True,
        })),
        ("snapshot", envelope("snapshot", "snapshot-1", {
            "surface": "session", "cursor": 42, "records": [
                {"id": "s-1", "title": "Session one", "active": True},
                {"id": "s-2", "title": "Session two", "active": False},
            ],
        }, "subscribe-1")),
        ("event", envelope("event", "event-1", {
            "surface": "conversation", "cursor": 43,
            "delta": {"op": "append", "record": {
                "id": "m-9", "role": "assistant", "text": "done",
            }},
        })),
        ("surface_snapshot", envelope("surface_snapshot", "surface-snapshot-1", {
            "surface": "terminal", "cursor": 7,
            "state": {"rows": 24, "columns": 80, "lines": ["$ birkin status"]},
        })),
        ("surface_event", envelope("surface_event", "surface-event-1", {
            "surface": "terminal", "cursor": 8,
            "patch": {"op": "line", "index": 0, "text": "$ birkin run"},
        })),
        ("command", envelope("command", "command-1", {
            "session_capability": "cap-token-1", "command": command_body,
        })),
        ("receipt", envelope(
            "receipt", "receipt-1", receipt_body, "command-1"
        )),
        ("error", envelope("error", "error-1", {
            "code": "E_UNSUPPORTED_COMMAND", "message": "unsupported command",
            "retryable": False,
        }, "command-1")),
        ("capability_renewed", envelope("capability.renewed", "capability-1", {
            "token": "cap-token-2", "expires_at": "2026-08-20T13:00:00+00:00",
            "hard_expires_at": "2026-08-20T18:00:00+00:00",
        })),
        ("stream_desynchronized", envelope("stream.desynchronized", "desync-1", {
            "surface": "conversation", "expected_cursor": 44,
            "received_cursor": 51, "action": "resubscribe",
        })),
        ("ping", envelope("ping", "ping-1", {"nonce": "n-1"})),
        ("pong", envelope("pong", "pong-1", {"nonce": "n-1"}, "ping-1")),
        ("goodbye", envelope("goodbye", "goodbye-1", {"reason": "client_exit"})),
        ("empty_body", envelope("ping", "empty-1", {})),
    ]
    vectors.extend([
        ("unicode_and_escapes", envelope("event", "unicode-1", {
            "korean": "안녕하세요 버킨", "emoji": "🛰️ 작업 완료",
            "quotes": 'he said "hi" and left', "backslashes": "C:\\\\Users\\birkin",
            "whitespace": "tab\there\nnewline\r\n",
            "controls": "".join(chr(code) for code in range(0x20)),
            "delete_and_separators": "\x7f\u2028\u2029", "solidus": "a/b",
        })),
        ("numeric_edges", envelope("event", "numeric-1", {
            "zero": 0, "negative": -1, "large_int": 9007199254740993,
            "int64_min": -9223372036854775808, "one_point_zero": 1.0,
            "negative_zero": -0.0, "tenth": 0.1, "third": 1 / 3,
            "fixed_upper": 1e15, "exponent_upper": 1e16,
            "fixed_lower": 1e-4, "exponent_lower": 1e-5,
            "max_double": 1.7976931348623157e308, "min_subnormal": 5e-324,
            "mixed": [1, 1.5, -2.25, 1e100],
        })),
        ("maximum_depth", envelope("command", "depth-1", _nested_body(MAX_JSON_DEPTH - 2))),
        ("key_order", envelope("snapshot", "order-1", {
            "zulu": 1, "alpha": 2, "mike": 3,
            "bravo": {"zeta": 1, "alpha": 2},
        })),
        ("bounded_identifiers", envelope(
            "receipt", "i" * 128, bounded_receipt_body, "a.b:c-d_e"
        )),
    ])
    return vectors


def _frame(body: bytes, *, declared: int | None = None) -> bytes:
    length = len(body) if declared is None else declared
    return struct.pack(">I", length) + body


def build_invalid_vectors() -> list[InvalidVector]:
    """Return raw frames spanning Python's stable framing/parser refusals."""
    valid = (
        b'{"protocol":"birkin-local-1","protocol_version":1,'
        b'"kind":"ping","id":"invalid-1","in_reply_to":null,"body":{}}'
    )
    nested_body = b'{"child":' * MAX_JSON_DEPTH + b'{}' + b'}' * MAX_JSON_DEPTH
    parser_depth = b'{"value":' + b'[' * 129 + b'0' + b']' * 129 + b'}'
    cases = [
        ("incomplete_header", "frame_length", b"\x00\x00\x00", "E_FRAME_INCOMPLETE"),
        ("incomplete_body", "frame_length", _frame(b"{}", declared=3), "E_FRAME_INCOMPLETE"),
        ("oversized_declared_body", "frame_length", _frame(b"", declared=MAX_FRAME_BYTES + 1), "E_FRAME_TOO_LARGE"),
        ("trailing_data", "frame_length", _frame(valid) + b" ", "E_FRAME_TRAILING_DATA"),
        ("invalid_utf8", "utf8", _frame(b"\xff"), "E_INVALID_UTF8"),
        ("malformed_json", "json_syntax", _frame(b"{"), "E_JSON"),
        ("non_object_envelope", "envelope_shape", _frame(b"[]"), "E_JSON"),
        ("duplicate_object_key", "duplicate_key", _frame(valid.replace(b'"kind":"ping"', b'"kind":"ping","kind":"pong"')), "E_DUPLICATE_KEY"),
        ("lone_surrogate", "unicode", _frame(valid.replace(b"{}", b'{"value":"\\ud800"}')), "E_JSON"),
        ("nonfinite_number", "number", _frame(valid.replace(b"{}", b'{"value":NaN}')), "E_NONFINITE_NUMBER"),
        ("signed_64_overflow", "number", _frame(valid.replace(b"{}", b'{"value":1180591620717411303424}')), "E_JSON"),
        ("parser_depth", "json_depth", _frame(valid.replace(b"{}", parser_depth)), "E_JSON_DEPTH"),
        ("body_depth", "json_depth", _frame(valid.replace(b"{}", nested_body)), "E_JSON_DEPTH"),
        ("missing_protocol_version", "envelope_keys", _frame(valid.replace(b'"protocol_version":1,', b"")), "E_ENVELOPE_KEYS"),
        ("unsupported_protocol_version", "protocol_version", _frame(valid.replace(b'"protocol_version":1', b'"protocol_version":2')), "E_PROTOCOL_VERSION"),
        ("invalid_protocol_version_type", "protocol_version", _frame(valid.replace(b'"protocol_version":1', b'"protocol_version":"1"')), "E_PROTOCOL_VERSION"),
        ("missing_message_type", "envelope_keys", _frame(valid.replace(b'"kind":"ping",', b"")), "E_ENVELOPE_KEYS"),
        ("invalid_message_type", "message_type", _frame(valid.replace(b'"kind":"ping"', b'"kind":"invented"')), "E_KIND"),
        ("invalid_identifier", "identifier", _frame(valid.replace(b'"id":"invalid-1"', b'"id":"contains space"')), "E_IDENTIFIER"),
        ("non_object_body", "body_shape", _frame(valid.replace(b'"body":{}', b'"body":[]')), "E_JSON"),
    ]
    return [InvalidVector(*case) for case in cases]
