"""The LSP wire format, and what counts as a NEW diagnostic.

A language server speaks JSON-RPC framed with a ``Content-Length`` header over
stdio. Two details in that sentence are where implementations go wrong, so both
are pinned by tests here:

* the length counts **bytes, not characters**. A diagnostic reading
  "정의되지 않은 이름" is 27 bytes and 9 characters; sending the character count
  desynchronises the stream permanently, and every later message is garbage.
* a truncated body is an error, never a short read. Silently accepting fewer
  bytes than declared turns one dropped packet into a parser that never
  recovers.

Pure standard library, and no I/O of its own beyond the stream it is handed.
"""

from __future__ import annotations

import json
from typing import Any, BinaryIO, Optional

_ENCODING = "utf-8"


class LspError(RuntimeError):
    """A language server could not be started, framed, or answered in time."""


def encode(payload: dict[str, Any]) -> bytes:
    """One framed message: header, blank line, UTF-8 JSON body."""
    body = json.dumps(payload, ensure_ascii=False).encode(_ENCODING)
    return b"Content-Length: %d\r\n\r\n%s" % (len(body), body)


def read_message(stream: BinaryIO) -> Optional[dict[str, Any]]:
    """The next message, or ``None`` once the stream is closed.

    Unknown headers are skipped: servers send ``Content-Type`` and some send
    vendor headers, and a client that trips over them works against exactly one
    implementation.
    """
    length: Optional[int] = None
    saw_header = False
    while True:
        line = stream.readline()
        if not line:
            if saw_header:
                raise LspError("stream closed inside a message header")
            return None
        saw_header = True
        stripped = line.strip()
        if not stripped:
            break
        name, _, value = stripped.decode("ascii", "replace").partition(":")
        if name.strip().lower() == "content-length":
            try:
                length = int(value.strip())
            except ValueError:
                raise LspError(f"unparseable Content-Length: {value!r}")
    if length is None:
        raise LspError("message header carried no Content-Length")
    body = stream.read(length)
    if body is None or len(body) < length:
        raise LspError(
            f"truncated body: declared {length} bytes, read "
            f"{0 if body is None else len(body)}")
    try:
        return json.loads(body.decode(_ENCODING, "replace"))
    except ValueError as exc:
        raise LspError(f"malformed JSON body: {exc}")


def _identity(diagnostic: dict[str, Any]) -> tuple:
    """What makes two diagnostics the same one.

    Position is part of it. "unused import" on line 7 and the same text on line
    40 are two different problems, and an edit that moves one must report it.
    """
    start = ((diagnostic.get("range") or {}).get("start") or {})
    return (start.get("line"), start.get("character"),
            diagnostic.get("code"), diagnostic.get("message"),
            diagnostic.get("severity"))


def new_since(baseline: list[dict[str, Any]],
              current: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Diagnostics in ``current`` that the baseline did not already have.

    Without this an edit to a file that already had ten warnings reports all
    ten as if this edit caused them, and the one that matters is invisible.
    """
    known = {_identity(d) for d in baseline or []}
    return [d for d in current or [] if _identity(d) not in known]
