from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from birkin.profile_migration import (
    LegacyPreference,
    migrate_legacy_preferences,
    rollback_legacy_preferences,
)
from birkin.rolefiles import ProfileEdit, ProfileStore


def note(name: str, body: str) -> LegacyPreference:
    key = name.lower().replace(" ", "-")
    return LegacyPreference(path=f"vault/{key}.md", title=f"Profile - {name}", body=body)


def test_migration_is_idempotent_across_repeated_runs(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path, {})
    archived: list[LegacyPreference] = []
    notes = [note("language", "Korean replies"), note("tone", "concise")]

    first = migrate_legacy_preferences(store, notes, archive=archived.append)
    manifest = tmp_path / "profile" / "migration-v1.json"
    before = hashlib.sha256(manifest.read_bytes()).hexdigest()
    second = migrate_legacy_preferences(store, notes, archive=archived.append)
    after = hashlib.sha256(manifest.read_bytes()).hexdigest()

    entries = store.snapshot().documents["preferences"].entries
    manifest_data = manifest.read_text(encoding="utf-8")
    assert '"body"' not in manifest_data
    assert "Korean replies" not in manifest_data
    assert entries == ("language: Korean replies", "tone: concise")
    assert first.archived == 2
    assert first.unchanged == 0
    assert second.archived == 0
    assert second.migrated == 0
    assert second.unchanged == 2
    assert before == after
    assert len(archived) == 2


def test_crash_after_role_entry_written_resumes_archive(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path, {})
    source = note("format", "bullets first")
    calls = 0
    archived: list[LegacyPreference] = []

    def crash_once(item: LegacyPreference) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("boom")
        archived.append(item)

    with pytest.raises(RuntimeError):
        migrate_legacy_preferences(store, [source], archive=crash_once)

    assert "format: bullets first" in store.snapshot().documents["preferences"].entries
    report = migrate_legacy_preferences(store, [source], archive=crash_once)
    assert report.archived == 1
    assert report.unchanged == 0
    assert archived == [source]


def test_conflicting_values_stay_pending_and_sources_are_not_archived(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path, {})
    store.apply(ProfileEdit("preferences", "add", content="tone: concise"))
    archived: list[LegacyPreference] = []

    report = migrate_legacy_preferences(
        store, [note("tone", "verbose explanations")], archive=archived.append
    )

    assert report.pending == 1
    assert archived == []
    assert store.snapshot().documents["preferences"].entries == ("tone: concise",)


def test_rollback_restores_only_archived_notes_and_is_repeat_noop(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path, {})
    archived_note = note("language", "Korean replies")
    pending_note = note("tone", "verbose")
    store.apply(ProfileEdit("preferences", "add", content="tone: concise"))
    archived: list[LegacyPreference] = []
    restored: list[LegacyPreference] = []

    migrate_legacy_preferences(store, [archived_note, pending_note], archive=archived.append)
    archived_by_title = {item.title: item for item in archived}
    first = rollback_legacy_preferences(
        store,
        restore=restored.append,
        archived=lambda item: archived_by_title.get(item.title),
    )
    second = rollback_legacy_preferences(
        store,
        restore=restored.append,
        archived=lambda item: archived_by_title.get(item.title),
    )

    assert archived == [archived_note]
    assert restored == [archived_note]
    assert first.restored == 1
    assert second.restored == 0
    assert second.unchanged == 1
    assert "language: Korean replies" in store.snapshot().documents["preferences"].entries


def test_rollback_reports_deleted_archive_as_unrestorable_without_restore(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path, {})
    archived_note = note("language", "Korean replies")
    archived: list[LegacyPreference] = []
    restored: list[LegacyPreference] = []

    migrate_legacy_preferences(store, [archived_note], archive=archived.append)
    first = rollback_legacy_preferences(store, restore=restored.append, archived=lambda _item: None)
    second = rollback_legacy_preferences(store, restore=restored.append, archived=lambda _item: None)

    assert archived == [archived_note]
    assert restored == []
    assert first.unrestorable == 1
    assert first.restored == 0
    assert second.restored == 0
    assert second.unrestorable == 0
    assert second.unchanged == 0
