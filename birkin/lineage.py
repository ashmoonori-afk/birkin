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
import re
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from . import config

_SNAPSHOT_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{8}$")


def _dir() -> Path:
    d = config.birkin_home() / "lineage"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _validate_id(snapshot_id: str) -> str:
    if not _SNAPSHOT_ID.fullmatch(snapshot_id):
        raise ValueError("invalid snapshot id")
    return snapshot_id


def _read(snapshot_id: str) -> Optional[dict[str, Any]]:
    try:
        validated = _validate_id(snapshot_id)
    except ValueError:
        return None
    try:
        raw = (_dir() / f"{validated}.json").read_text(encoding="utf-8")
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
    if parent is not None and not _SNAPSHOT_ID.fullmatch(parent):
        return None
    record = {
        "schema": 1,
        "trusted": True,
        "id": sid,
        "parent": parent,
        "reason": reason,
        "created": time.time(),
        "messages": messages,
    }
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


def list_snapshots() -> list[dict[str, Any]]:
    """Trusted snapshot metadata, newest first."""
    entries: list[dict[str, Any]] = []
    for path in _dir().glob("*.json"):
        record = _read(path.stem)
        if record is None:
            continue
        trusted = record.get("trusted", True)
        if trusted is not True:
            continue
        snapshot_id = record.get("id")
        created = record.get("created")
        if snapshot_id != path.stem or not isinstance(created, (int, float)):
            continue
        entries.append(
            {
                "id": snapshot_id,
                "parent": record.get("parent"),
                "reason": record.get("reason"),
                "created": float(created),
                "trusted": True,
            }
        )
    return sorted(
        entries,
        key=lambda entry: (entry["created"], entry["id"]),
        reverse=True,
    )


def recover(snapshot_id: str) -> list[dict[str, Any]]:
    """Return trusted messages or raise for invalid/unknown snapshots."""
    _validate_id(snapshot_id)
    record = _read(snapshot_id)
    if record is None or record.get("trusted", True) is not True:
        raise ValueError("unknown trusted snapshot id")
    messages = record.get("messages")
    if not isinstance(messages, list) or not all(
        isinstance(message, dict) for message in messages
    ):
        raise ValueError("snapshot messages are malformed")
    return messages


def export_snapshot(snapshot_id: str, destination: Path) -> Path:
    """Export one trusted record to an explicit JSON file."""
    _ = recover(snapshot_id)
    record = _read(snapshot_id)
    if record is None:
        raise ValueError("unknown trusted snapshot id")
    target = Path(destination)
    if target.exists() and target.is_dir():
        raise ValueError("export destination must be a file")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def prune(*, keep: int) -> list[str]:
    """Delete all but the newest ``keep`` trusted snapshots."""
    if keep < 0:
        raise ValueError("keep must be non-negative")
    removed: list[str] = []
    for entry in list_snapshots()[keep:]:
        snapshot_id = str(entry["id"])
        try:
            (_dir() / f"{snapshot_id}.json").unlink()
        except FileNotFoundError:
            continue
        removed.append(snapshot_id)
    return removed
