"""Strict persistence tests for tool effect attestations."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from birkin.tool_attestations import AttestationError, ToolAttestationStore
from birkin.tool_effects import InspectGrant, PluginToolId

DIGEST = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
STAMP = "2026-08-21T12:00:00Z"


def grant(*, plugin: str = "plugin-agent", tool: str = "plugin_echo") -> InspectGrant:
    return InspectGrant(
        PluginToolId(plugin, "1.0.0", DIGEST, tool), True,
        "reviewed handler; no writes", STAMP,
    )


def payload(entries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if entries is None:
        entries = [{
            "bundle_digest": DIGEST,
            "parallel_safe": True,
            "plugin": "plugin-agent",
            "plugin_version": "1.0.0",
            "reason": "reviewed handler; no writes",
            "recorded_at": STAMP,
            "tool": "plugin_echo",
        }]
    return {"schema_version": 1, "inspect_grants": entries}


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_missing_file_returns_empty_snapshot_without_creating_file(tmp_path: Path) -> None:
    path = tmp_path / "tool-effects.json"
    snapshot = ToolAttestationStore(path).load()
    assert snapshot.state == "missing"
    assert snapshot.grants == ()
    assert not path.exists()


def test_valid_file_round_trips_in_canonical_sorted_form(tmp_path: Path) -> None:
    path = tmp_path / "tool-effects.json"
    store = ToolAttestationStore(path)
    grants = (grant(plugin="zeta", tool="a"), grant(plugin="alpha", tool="z"))
    store.write(grants)
    expected = json.dumps(
        payload([
            {**payload()["inspect_grants"][0], "plugin": "alpha", "tool": "z"},
            {**payload()["inspect_grants"][0], "plugin": "zeta", "tool": "a"},
        ]), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    assert path.read_text(encoding="utf-8") == expected
    assert store.load().grants == (grants[1], grants[0])


def test_malformed_json_and_duplicate_key_invalidate_all_grants(tmp_path: Path) -> None:
    path = tmp_path / "tool-effects.json"
    path.write_text("{oops}", encoding="utf-8")
    snapshot = ToolAttestationStore(path).load()
    assert snapshot.state == "invalid" and snapshot.grants == ()
    assert snapshot.diagnostic == "invalid JSON at line 1 column 2"

    path.write_text('{"schema_version":1,"schema_version":1,"inspect_grants":[]}',
                    encoding="utf-8")
    snapshot = ToolAttestationStore(path).load()
    assert snapshot.state == "invalid" and snapshot.grants == ()
    assert "duplicate JSON key" in snapshot.diagnostic


def test_duplicate_identity_and_unknown_schema_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "tool-effects.json"
    entry = payload()["inspect_grants"][0]
    write_json(path, payload([entry, dict(entry)]))
    assert "duplicate grant identity" in ToolAttestationStore(path).load().diagnostic
    write_json(path, {"schema_version": 2, "inspect_grants": []})
    assert "schema version" in ToolAttestationStore(path).load().diagnostic


@pytest.mark.parametrize(("field", "value"), [
    ("bundle_digest", "A" * 64),
    ("reason", ""),
    ("reason", "has\ncontrol"),
    ("recorded_at", "2026-08-21T12:00:00+00:00"),
    ("parallel_safe", "true"),
])
def test_invalid_grant_fields_reject_whole_file(
    tmp_path: Path, field: str, value: Any,
) -> None:
    path = tmp_path / "tool-effects.json"
    entry = {**payload()["inspect_grants"][0], field: value}
    write_json(path, payload([entry]))
    snapshot = ToolAttestationStore(path).load()
    assert snapshot.state == "invalid" and snapshot.grants == ()


def test_unknown_fields_and_wrong_json_types_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "tool-effects.json"
    write_json(path, {**payload(), "extra": 1})
    assert ToolAttestationStore(path).load().state == "invalid"
    entry = {**payload()["inspect_grants"][0], "extra": 1}
    write_json(path, payload([entry]))
    assert ToolAttestationStore(path).load().state == "invalid"
    write_json(path, {"schema_version": True, "inspect_grants": []})
    assert ToolAttestationStore(path).load().state == "invalid"


def test_file_and_grant_count_limits_are_enforced(tmp_path: Path) -> None:
    path = tmp_path / "tool-effects.json"
    path.write_bytes(b" " * (1024 * 1024 + 1))
    assert "1 MiB" in ToolAttestationStore(path).load().diagnostic
    write_json(path, payload([{}] * 4097))
    assert "4096" in ToolAttestationStore(path).load().diagnostic


def test_symlinks_and_non_regular_files_are_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    write_json(target, payload([]))
    link = tmp_path / "tool-effects.json"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    assert ToolAttestationStore(link).load().state == "invalid"
    with pytest.raises(AttestationError):
        ToolAttestationStore(link).write(())


def test_atomic_write_failure_preserves_previous_file_and_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tool-effects.json"
    store = ToolAttestationStore(path)
    store.write((grant(),))
    previous = path.read_bytes()

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("disk failed")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="disk failed"):
        store.write(())
    assert path.read_bytes() == previous
    assert not list(tmp_path.glob(".tool-effects.json.*.tmp"))


def test_atomic_temp_is_exclusive_owner_only_flushed_and_fsynced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tool-effects.json"
    opens: list[tuple[int, int]] = []
    fsyncs: list[int] = []
    real_open, real_fsync = os.open, os.fsync

    def recording_open(name: Any, flags: int, mode: int = 0o777) -> int:
        opens.append((flags, mode))
        return real_open(name, flags, mode)

    def recording_fsync(fd: int) -> None:
        fsyncs.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "open", recording_open)
    monkeypatch.setattr(os, "fsync", recording_fsync)
    ToolAttestationStore(path).write(())
    flags, mode = opens[0]
    assert flags & os.O_CREAT and flags & os.O_EXCL
    assert mode == 0o600 and fsyncs


def test_reset_finishes_backup_before_replacing_live_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tool-effects.json"
    original = b"{malformed but precious"
    path.write_bytes(original)
    events: list[tuple[str, Path, bytes | None]] = []
    real_replace = os.replace

    def recording_replace(source: Path, destination: Path) -> None:
        dest = Path(destination)
        events.append(("replace", dest, path.read_bytes() if path.exists() else None))
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", recording_replace)
    backup = ToolAttestationStore(path).reset()
    assert backup == path.with_name("tool-effects.json.previous")
    assert backup.read_bytes() == original
    assert ToolAttestationStore(path).load().grants == ()
    assert [event[1] for event in events] == [backup, path]
    assert events[1][2] == original


def test_reset_backup_failure_leaves_live_file_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tool-effects.json"
    original = b"broken"
    path.write_bytes(original)

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("backup failed")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="backup failed"):
        ToolAttestationStore(path).reset()
    assert path.read_bytes() == original
