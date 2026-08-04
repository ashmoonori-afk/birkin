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

That tolerance was per-*crash*. It became per-*process* the moment two gateways
ran at once: both read the same backlog and both sent it. A claim fixes that --
one owner takes a row, the others see nothing to do -- and an attempt counter
records the rows that keep failing instead of retrying them invisibly forever.
A claim left behind by a daemon that died mid-send expires, so a crash cannot
wedge a reply permanently either. Same four columns hermes carries on its
async_delegations table (delivery_state / delivery_attempts / delivery_claim /
delivery_claimed_at).
"""

from __future__ import annotations

import os
import sqlite3
import time
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
  created TEXT NOT NULL,
  delivery_state      TEXT NOT NULL DEFAULT 'pending',
  delivery_attempts   INTEGER NOT NULL DEFAULT 0,
  delivery_claim      TEXT,
  delivery_claimed_at REAL
);
"""
# The index deliberately lives in _migrate, not here: _SCHEMA runs first, and on
# an outbox written before the claim columns existed an index over
# delivery_state would reference a column that is added a moment later. That
# statement raised, pending() swallowed it, and a user's owed replies read as
# empty -- losing exactly the rows this module exists to protect.

# How long a claim is honoured before another process may take the row. A
# daemon that dies mid-send would otherwise hold it forever.
CLAIM_STALE_SECONDS = 300.0


def _path() -> Path:
    return config.birkin_home() / "delivery.db"


_NEW_COLUMNS = (
    ("delivery_state", "TEXT NOT NULL DEFAULT 'pending'"),
    ("delivery_attempts", "INTEGER NOT NULL DEFAULT 0"),
    ("delivery_claim", "TEXT"),
    ("delivery_claimed_at", "REAL"),
)


def _migrate(con: sqlite3.Connection) -> None:
    """Add the claim columns to an outbox written before they existed.

    A user upgrading birkin already has a delivery.db, possibly with replies
    owed in it. Recreating the table would drop exactly the rows this module
    exists to protect, so the columns are added in place.
    """
    present = {row[1] for row in con.execute("PRAGMA table_info(outbox)")}
    for name, ddl in _NEW_COLUMNS:
        if name not in present:
            con.execute(f"ALTER TABLE outbox ADD COLUMN {name} {ddl}")
    con.execute("CREATE INDEX IF NOT EXISTS idx_outbox_delivery "
                "ON outbox (delivery_state, id)")


def _default_owner() -> str:
    """Identity of the claiming process -- the pid is the discriminator."""
    return f"pid:{os.getpid()}"


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(_path(), timeout=5.0)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(_SCHEMA)
    _migrate(con)
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


def claim(channel: str, *, owner: str | None = None,
          stale_after: float = CLAIM_STALE_SECONDS) -> list[dict[str, Any]]:
    """Take exclusive responsibility for ``channel``'s outstanding replies.

    Returns the rows this caller now owns; a concurrent claimer sees none of
    them. A claim older than ``stale_after`` is taken over, so a daemon that
    died mid-send cannot hold a reply hostage.

    Each returned row carries ``delivery_attempts`` as it stood *before* this
    claim, so a caller can tell a first try from a tenth.
    """
    owner = owner or _default_owner()
    now = time.time()
    cutoff = now - max(0.0, float(stale_after))
    try:
        with closing(_connect()) as con, con:
            con.row_factory = sqlite3.Row
            rows = [dict(r) for r in con.execute(
                "SELECT * FROM outbox WHERE channel = ? AND ("
                "delivery_state != 'claimed' OR delivery_claimed_at IS NULL "
                "OR delivery_claimed_at <= ?) ORDER BY id",
                (str(channel), cutoff)).fetchall()]
            for row in rows:
                con.execute(
                    "UPDATE outbox SET delivery_state = 'claimed', "
                    "delivery_claim = ?, delivery_claimed_at = ?, "
                    "delivery_attempts = delivery_attempts + 1 "
                    "WHERE id = ?", (owner, now, int(row["id"])))
            return rows
    except Exception:
        return []


def release(row_id: int | None) -> None:
    """Hand a claimed row back -- the send definitely failed.

    The attempt already counted stays counted; only the ownership is dropped,
    so the next boot retries promptly instead of waiting out the stale window.
    """
    if row_id is None:
        return
    try:
        with closing(_connect()) as con, con:
            con.execute(
                "UPDATE outbox SET delivery_state = 'pending', "
                "delivery_claim = NULL, delivery_claimed_at = NULL "
                "WHERE id = ?", (int(row_id),))
    except Exception:
        pass


def redeliver(channel: str, send: Any, *, prefix: str = "[재전송] ",
              owner: str | None = None) -> int:
    """Send every outstanding reply for ``channel``; returns how many went out.

    Rows are claimed first, so a second gateway running the same recovery sends
    nothing rather than duplicating the backlog.

    ``send(chat_id, text)`` may return ``False`` when it definitely did not
    deliver. Other falsey values preserve compatibility with senders that do
    not return a status.
    """
    sent = 0
    for row in claim(channel, owner=owner):
        try:
            delivered = send(row["chat_id"], prefix + row["text"])
        except Exception:
            release(row["id"])       # leave it recorded; try again next boot
            continue
        if delivered is False:
            release(row["id"])
            continue
        sent += 1
        clear(row["id"])
    return sent
