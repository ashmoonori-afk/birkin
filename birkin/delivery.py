"""Delivery obligations — a finished reply must survive a gateway crash.

The gateway spends the expensive part of a turn producing a reply and only
then hands it to a channel to send. If the process dies in that window the
answer is gone: the user sees silence, and the tokens are already spent. The
channel's own retry does not help — it never received the text.

So the obligation is recorded first and cleared after the send succeeds. On
the next boot anything still recorded is redelivered, marked so the user knows
why a message arrived late. One WAL-mode SQLite file (stdlib ``sqlite3``,
same pattern as :mod:`birkin.ledger`), because a crash-durability record that
itself needs a clean shutdown would be pointless.

Deliberately at-least-once: a crash *after* the platform accepted the message
but *before* the row was cleared redelivers it. A duplicate is recoverable by
a human reading it; a silently lost answer is not.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS outbox (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  channel TEXT NOT NULL,
  chat_id TEXT NOT NULL,
  text    TEXT NOT NULL,
  created TEXT NOT NULL
);
"""


def _path() -> Path:
    return config.birkin_home() / "delivery.db"


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(_path(), timeout=5.0)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(_SCHEMA)
    return con


def record(channel: str, chat_id: str, text: str) -> int | None:
    """Take on the obligation to deliver ``text``. Returns a row id.

    Never raises: failing to record must not cost the user their reply.
    """
    if not (text or "").strip():
        return None
    try:
        with closing(_connect()) as con, con:
            cur = con.execute(
                "INSERT INTO outbox (channel, chat_id, text, created) "
                "VALUES (?, ?, ?, ?)",
                (str(channel), str(chat_id), str(text),
                 datetime.now(timezone.utc).isoformat(timespec="seconds")))
            return int(cur.lastrowid)
    except Exception:
        return None


def clear(row_id: int | None) -> None:
    """Discharge the obligation — the send succeeded."""
    if row_id is None:
        return
    try:
        with closing(_connect()) as con, con:
            con.execute("DELETE FROM outbox WHERE id = ?", (int(row_id),))
    except Exception:
        pass


def pending(channel: str | None = None) -> list[dict[str, Any]]:
    """Obligations that outlived the process that took them on."""
    try:
        with closing(_connect()) as con, con:
            con.row_factory = sqlite3.Row
            if channel:
                rows = con.execute(
                    "SELECT * FROM outbox WHERE channel = ? ORDER BY id",
                    (str(channel),)).fetchall()
            else:
                rows = con.execute(
                    "SELECT * FROM outbox ORDER BY id").fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def redeliver(channel: str, send: Any, *, prefix: str = "[재전송] ") -> int:
    """Send every outstanding reply for ``channel``; returns how many went out.

    ``send(chat_id, text)`` should return falsey only when it definitely did
    not deliver — a row is cleared unless the send raises, so a permanently
    failing chat cannot wedge the boot path forever.
    """
    sent = 0
    for row in pending(channel):
        try:
            send(row["chat_id"], prefix + row["text"])
            sent += 1
        except Exception:
            continue                 # leave it recorded; try again next boot
        clear(row["id"])
    return sent
