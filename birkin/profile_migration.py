"""Migration from legacy preference notes into role-profile files."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .rolefiles import ProfileBudgetExceeded, ProfileEdit, ProfileStore


@dataclass(frozen=True)
class LegacyPreference:
    """One legacy vault note that may represent a profile preference."""

    path: str
    title: str
    body: str
    zone: str = "identity"
    type: str = "preference"


@dataclass(frozen=True)
class MigrationReport:
    """Summary of one migration or rollback pass."""

    considered: int = 0
    migrated: int = 0
    archived: int = 0
    pending: int = 0
    restored: int = 0
    unchanged: int = 0
    completed: bool = False


def migrate_legacy_preferences(
    store: ProfileStore,
    notes: Iterable[LegacyPreference],
    *,
    archive: Callable[[LegacyPreference], None],
) -> MigrationReport:
    """Move eligible ``Profile - *`` preference notes into ``preferences.md``."""
    manifest = _load(_manifest_path(store))
    source_notes = [_coerce(note) for note in notes if _eligible(_coerce(note))]
    records = manifest.setdefault("sources", {})
    considered = migrated = archived = pending = unchanged = 0
    dirty = False
    for note in source_notes:
        considered += 1
        key = _source_key(note)
        entry = _entry(note)
        digest = _hash(note.body)
        record = records.get(key)
        if record and record.get("hash") != digest:
            record["status"] = "pending"
            record["reason"] = "source changed"
            pending += 1
            dirty = True
            _save(store, manifest)
            continue
        if record is None:
            record = {
                "path": note.path,
                "title": note.title,
                "body": note.body,
                "zone": note.zone,
                "type": note.type,
                "hash": digest,
                "target": "preferences",
                "entry": entry,
                "status": "pending",
            }
            records[key] = record
            dirty = True
            _save(store, manifest)
        if record.get("status") in {"archived", "rolled_back"}:
            unchanged += 1
            continue
        if not _present(store, entry):
            if _conflicts(store, note, entry):
                record["status"] = "pending"
                record["reason"] = "conflict"
                pending += 1
                dirty = True
                _save(store, manifest)
                continue
            try:
                store.apply(ProfileEdit("preferences", "add", content=entry))
            except ProfileBudgetExceeded:
                record["status"] = "pending"
                record["reason"] = "budget"
                pending += 1
                dirty = True
                _save(store, manifest)
                continue
            migrated += 1
            record["status"] = "written"
            dirty = True
            _save(store, manifest)
        if _present(store, entry):
            archive(note)
            archived += 1
            record["status"] = "archived"
            dirty = True
            _save(store, manifest)
    total = len(records)
    completed = total > 0 and all(
        record.get("status") in {"archived", "rolled_back"}
        for record in records.values()
    )
    if manifest.get("completed") != completed:
        manifest["completed"] = completed
        dirty = True
    if dirty:
        _save(store, manifest)
    pending = sum(1 for record in records.values() if record.get("status") == "pending")
    return MigrationReport(
        considered=considered,
        migrated=migrated,
        archived=archived,
        pending=pending,
        unchanged=unchanged,
        completed=completed,
    )


def rollback_legacy_preferences(
    store: ProfileStore,
    *,
    restore: Callable[[LegacyPreference], None],
) -> MigrationReport:
    """Restore only notes archived by this migration manifest."""
    manifest = _load(_manifest_path(store))
    restored = 0
    for record in manifest.get("sources", {}).values():
        if record.get("status") != "archived":
            continue
        note = LegacyPreference(
            path=str(record["path"]),
            title=str(record.get("title", _title(str(record["path"])))),
            body=str(record.get("body", "")),
            zone=str(record.get("zone", "identity")),
            type=str(record.get("type", "preference")),
        )
        restore(note)
        restored += 1
        record["status"] = "rolled_back"
    manifest["completed"] = all(
        record.get("status") in {"rolled_back", "pending"}
        for record in manifest.get("sources", {}).values()
    )
    _save(store, manifest)
    return MigrationReport(restored=restored, completed=bool(manifest.get("completed")))


def _eligible(note: LegacyPreference) -> bool:
    return note.type == "preference" and note.title.startswith("Profile - ")


def _entry(note: LegacyPreference) -> str:
    key = note.title.removeprefix("Profile - ").strip()
    value = " ".join(note.body.split())
    return f"{key}: {value}" if key else value


def _conflicts(store: ProfileStore, note: LegacyPreference, entry: str) -> bool:
    key = note.title.removeprefix("Profile - ").strip()
    prefix = f"{key}:"
    for current in store.snapshot().documents["preferences"].entries:
        if current == entry:
            return False
        if key and current.startswith(prefix):
            return True
    return False


def _present(store: ProfileStore, entry: str) -> bool:
    return entry in store.snapshot().documents["preferences"].entries


def _coerce(note: LegacyPreference) -> LegacyPreference:
    return note


def _manifest_path(store: ProfileStore) -> Path:
    return store.root / "migration-v1.json"


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "completed": False, "sources": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _save(store: ProfileStore, manifest: dict[str, Any]) -> None:
    path = _manifest_path(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".migration-v1.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _source_key(note: LegacyPreference) -> str:
    return _hash(f"{note.path}\0{note.title}")


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _title(path: str) -> str:
    return Path(path).stem
