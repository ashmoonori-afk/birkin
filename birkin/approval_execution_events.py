"""Framed progress events crossing the approval helper process boundary."""

from __future__ import annotations

import os
import sys
from typing import BinaryIO

from .approval_execution_codec import JournalCodecError, canonical, json_mapping
from .approval_execution_types import EventSink

EVENT_FRAME_PREFIX = b"\x1eBIRKIN_APPROVAL_EVENT "


def event_frame(*args: object) -> bytes:
    """Encode one helper observer call as a canonical, self-identifying frame."""
    try:
        payload = canonical(
            {
                "args": list(args),
                "kind": "event",
                "version": 1,
            }
        )
    except (TypeError, ValueError) as exc:
        payload = canonical(
            {
                "kind": "diagnostic",
                "message": f"approval event could not be encoded: {exc}",
                "version": 1,
            }
        )
    return EVENT_FRAME_PREFIX + payload + b"\n"


def emit_event(*args: object) -> None:
    """Write an observer call without letting transport failure affect the action."""
    try:
        sys.stdout.flush()
        _ = sys.stdout.buffer.write(event_frame(*args))
        sys.stdout.buffer.flush()
    except OSError as exc:
        _developer_diagnostic(f"event transport failed: {exc}")


def drain_helper_stdout(stream: BinaryIO, on_event: EventSink) -> None:
    """Drain helper output live so event frames cannot fill the child pipe."""
    pending = b""
    try:
        while chunk := os.read(stream.fileno(), 65536):
            pending = consume_helper_stdout(
                pending + chunk,
                on_event,
                final=False,
            )
    except OSError as exc:
        _developer_diagnostic(f"stdout drain failed: {exc}")
    _ = consume_helper_stdout(pending, on_event, final=True)


def consume_helper_stdout(
    data: bytes,
    on_event: EventSink,
    *,
    final: bool,
) -> bytes:
    """Dispatch complete event frames and retain only an incomplete suffix."""
    while data:
        marker = data.find(EVENT_FRAME_PREFIX)
        if marker < 0:
            if final:
                _stdout_diagnostic(data)
                return b""
            retained = _partial_prefix_length(data)
            if retained:
                _stdout_diagnostic(data[:-retained])
                return data[-retained:]
            _stdout_diagnostic(data)
            return b""
        if marker:
            _stdout_diagnostic(data[:marker])
            data = data[marker:]
        newline = data.find(b"\n", len(EVENT_FRAME_PREFIX))
        if newline < 0:
            if final:
                _developer_diagnostic("malformed event frame: incomplete frame")
                return b""
            return data
        frame = data[len(EVENT_FRAME_PREFIX):newline]
        data = data[newline + 1:]
        _dispatch_frame(frame, on_event)
    return b""


def _dispatch_frame(frame: bytes, on_event: EventSink) -> None:
    try:
        record = json_mapping(frame.decode("utf-8"))
    except (JournalCodecError, UnicodeDecodeError) as exc:
        _developer_diagnostic(f"malformed event frame: {exc}")
        return
    if record.get("version") != 1:
        _developer_diagnostic("malformed event frame: unsupported version")
        return
    if record.get("kind") == "diagnostic":
        _developer_diagnostic(str(record.get("message") or "helper diagnostic"))
        return
    args = record.get("args")
    if record.get("kind") != "event" or not isinstance(args, list):
        _developer_diagnostic("malformed event frame: invalid event record")
        return
    try:
        on_event(*args)
    except Exception as exc:
        _developer_diagnostic(
            f"event observer failed ({type(exc).__name__}): {exc}"
        )


def _partial_prefix_length(data: bytes) -> int:
    maximum = min(len(data), len(EVENT_FRAME_PREFIX) - 1)
    for length in range(maximum, 0, -1):
        if EVENT_FRAME_PREFIX.startswith(data[-length:]):
            return length
    return 0


def _developer_diagnostic(message: str) -> None:
    print(f"[approval helper] {message}", file=sys.stderr, flush=True)


def _stdout_diagnostic(data: bytes) -> None:
    if data:
        text = data.decode("utf-8", errors="replace").rstrip("\r\n")
        _developer_diagnostic(f"stdout: {text}")
