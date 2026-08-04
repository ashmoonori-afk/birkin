"""Recoverable snapshots of pre-compaction conversation history.

Compaction (compaction.py) replaces the middle of a long conversation with one
model-written summary. That keeps the chat alive past the context window, but
before this module it was *destructive*: the summarized turns existed nowhere
once the summary landed.

Every compaction now snapshots the full pre-compaction history to a file and
links it to the previous snapshot, so the chain of originals stays walkable
from the newest snapshot back to the first. Same idea as hermes-agent's
durable compression lineage (hermes_state.py, compression_close_and_publish /
parent_session_id chain), reimplemented over birkin's file-per-record storage
with the standard library only.

Durability is best-effort by design: a failed snapshot (full disk, locked
file) must never block the compaction that is saving the conversation from a
context overflow. Callers get ``None`` and carry on.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from . import config


def _dir() -> Path:
    d = config.birkin_home() / "lineage"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read(snapshot_id: str) -> Optional[dict[str, Any]]:
    try:
        raw = (_dir() / f"{snapshot_id}.json").read_text(encoding="utf-8")
        rec = json.loads(raw)
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) else None


def snapshot(messages: list[dict[str, Any]], *, parent: Optional[str] = None,
             reason: str = "compact") -> Optional[str]:
    """Persist ``messages`` and return the snapshot id (``None`` on failure).

    The input is serialized, never mutated or aliased.
    """
    sid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    record = {"id": sid, "parent": parent, "reason": reason,
              "created": time.time(), "messages": messages}
    try:
        body = json.dumps(record, ensure_ascii=False, default=str)
        (_dir() / f"{sid}.json").write_text(body, encoding="utf-8")
    except (OSError, ValueError):
        return None
    return sid


def load(snapshot_id: str) -> Optional[list[dict[str, Any]]]:
    """The messages a snapshot preserved, or ``None`` when it is unknown."""
    record = _read(snapshot_id)
    if record is None:
        return None
    messages = record.get("messages")
    return messages if isinstance(messages, list) else None


def chain(snapshot_id: str) -> list[str]:
    """Ancestor ids of ``snapshot_id``, oldest first. Cycle-guarded."""
    ancestors: list[str] = []
    seen = {snapshot_id}
    current = snapshot_id
    while True:
        record = _read(current)
        parent = record.get("parent") if record else None
        if not isinstance(parent, str) or parent in seen:
            break
        ancestors.append(parent)
        seen.add(parent)
        current = parent
    ancestors.reverse()
    return ancestors
