from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from birkin.office import retention, retention_backup_cleanup
from birkin.office.errors import DocumentError
from birkin.office.export_journal import ExportJournal
from birkin.office.export_policy import ExportRequest
from birkin.office.job_journal import OfficeJobJournal
from birkin.office.job_runner import DocumentServiceRunner
from birkin.office.retention import purge_expired_office_state
from birkin.office.service import DocumentService
from birkin.office.service_types import ArtifactRef
from birkin.office.service_workspace import DocumentWorkspace


@dataclass(frozen=True, slots=True)
class _Fixture:
    service: DocumentService
    destination: Path
    job_path: Path
    backup: Path
    transaction: Path
    expires: datetime


def test_retention_never_truncates_hardlink_peer(
    tmp_path: Path,
) -> None:
    backup = tmp_path / "backup.bak"
    peer = tmp_path / "peer.bin"
    payload = b"caller data"
    backup.write_bytes(payload)
    os.link(backup, peer)

    removed = retention_backup_cleanup.remove_authenticated_backup(
        backup,
        hashlib.sha256(payload).hexdigest(),
    )

    assert removed == 1
    assert not backup.exists()
    assert peer.read_bytes() == payload


def _validated_draft(service: DocumentService) -> ArtifactRef:
    workspace = DocumentWorkspace(service.home)
    output = workspace.output_path("validated.txt", ".txt")

    def write(target: Path) -> None:
        _ = target.write_text("retained export", encoding="utf-8")

    _ = workspace.atomic_publish(output, write)
    return workspace.artifact(output)


def _request(destination: Path) -> ExportRequest:
    return ExportRequest(
        destination=destination,
        actor="tester",
        proposal_digest="proposal",
        operations=({"op": "replace", "value": "retained export"},),
        overwrite_approved=True,
    )


def _fixture(tmp_path: Path) -> _Fixture:
    service = DocumentService(tmp_path / "office-home")
    caller = tmp_path / "caller"
    caller.mkdir()
    destination = caller / "result.txt"
    _ = destination.write_text("original bytes", encoding="utf-8")
    receipt = DocumentServiceRunner(service, export_root=caller).export(
        artifact=_validated_draft(service),
        request=_request(destination),
    )
    jobs = service.home / "jobs"
    jobs.mkdir()
    job_path = jobs / f"{'a' * 32}.jsonl"
    _ = job_path.write_text(
        json.dumps(
            {
                "job_id": "a" * 32,
                "state": "exported",
                "export": receipt,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    token = str(receipt["rollback_token"])
    return _Fixture(
        service=service,
        destination=destination,
        job_path=job_path,
        backup=service.home / "artifacts" / "export-backups" / f"{token}.bak",
        transaction=next(
            (service.home / "artifacts" / "export-journal").glob("*.json")
        ),
        expires=datetime.fromisoformat(
            str(receipt["expires_at"]).replace("Z", "+00:00")
        ),
    )


def test_retention_skips_job_removed_after_listing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    real_latest = OfficeJobJournal.latest
    removed = False

    def remove_before_latest(
        journal: OfficeJobJournal,
        job_id: str,
    ) -> dict[str, object]:
        nonlocal removed
        if not removed:
            removed = True
            fixture.job_path.unlink()
        return real_latest(journal, job_id)

    monkeypatch.setattr(OfficeJobJournal, "latest", remove_before_latest)

    purged = purge_expired_office_state(
        fixture.service.home,
        now=fixture.expires + timedelta(seconds=1),
    )

    assert purged == {"jobs": 0, "backups": 0, "transactions": 0}
    assert fixture.backup.exists()
    assert fixture.transaction.exists()


def test_retention_finishes_after_transaction_removed_during_purge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    real_load = ExportJournal.load
    removed = False

    def remove_before_load(
        journal: ExportJournal,
        key: str,
    ):
        nonlocal removed
        if not removed:
            removed = True
            journal.path_for(key).unlink()
        return real_load(journal, key)

    monkeypatch.setattr(ExportJournal, "load", remove_before_load)

    purged = purge_expired_office_state(
        fixture.service.home,
        now=fixture.expires + timedelta(seconds=1),
    )

    assert purged == {"jobs": 1, "backups": 1, "transactions": 0}
    assert not fixture.backup.exists()
    assert not fixture.job_path.exists()
    assert fixture.destination.read_text(encoding="utf-8") == "retained export"


def test_backup_cleanup_does_not_delete_swapped_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: two transactions own distinct rollback materials.
    backup_root = tmp_path / "export-backups"
    backup_root.mkdir()
    first = backup_root / f"{'a' * 32}.bak"
    second = backup_root / f"{'b' * 32}.bak"
    saved_first = backup_root / "saved-first.bak"
    first.write_bytes(b"first rollback material")
    second.write_bytes(b"second rollback material")
    real_unlink = Path.unlink

    def swap_other_backup(
        path: Path,
        missing_ok: bool = False,
    ) -> None:
        if path == first:
            first.rename(saved_first)
            second.rename(first)
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", swap_other_backup)

    # When: retention removes only the first transaction's backup.
    removed = retention._cleanup_backup(
        backup_root,
        first,
        hashlib.sha256(b"first rollback material").hexdigest(),
    )

    # Then: the second transaction's rollback material must survive.
    assert removed == 1
    assert second.read_bytes() == b"second rollback material"


def test_backup_cleanup_never_unlinks_swapped_quarantine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: authenticated quarantine can be replaced before pathname unlink.
    backup_root = tmp_path / "export-backups"
    backup_root.mkdir()
    first = backup_root / f"{'a' * 32}.bak"
    second = backup_root / f"{'b' * 32}.bak"
    quarantine = first.with_name(f".{first.name}.purge")
    saved_first = backup_root / "saved-first.purge"
    first.write_bytes(b"first rollback material")
    second.write_bytes(b"second rollback material")
    real_unlink = Path.unlink
    unlink_race_fired = False

    def swap_quarantine(
        path: Path,
        missing_ok: bool = False,
    ) -> None:
        nonlocal unlink_race_fired
        if path == quarantine:
            quarantine.rename(saved_first)
            second.rename(quarantine)
            unlink_race_fired = True
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", swap_quarantine)

    # When: retention purges the first authenticated material.
    removed = retention._cleanup_backup(
        backup_root,
        first,
        hashlib.sha256(b"first rollback material").hexdigest(),
    )

    # Then: no pathname unlink can target the second transaction.
    assert removed == 1
    assert unlink_race_fired is False
    assert second.read_bytes() == b"second rollback material"
    assert not quarantine.exists()
    retirement = backup_root / ".birkin-retire"
    if os.name == "nt":
        assert not retirement.exists()
    else:
        retired = tuple(retirement.iterdir())
        assert len(retired) == 1
        assert retired[0].read_bytes() == b"first rollback material"


def test_backup_cleanup_preserves_occupied_quarantine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: another writer claims the quarantine at the native move boundary.
    backup_root = tmp_path / "export-backups"
    backup_root.mkdir()
    backup = backup_root / f"{'a' * 32}.bak"
    quarantine = backup.with_name(f".{backup.name}.purge")
    payload = b"authenticated rollback material"
    backup.write_bytes(payload)
    real_move = retention_backup_cleanup.move_no_replace
    race_fired = False

    def occupy_before_move(source: Path, destination: Path) -> None:
        nonlocal race_fired
        destination.write_bytes(b"concurrent quarantine")
        race_fired = True
        real_move(source, destination)

    monkeypatch.setattr(
        retention_backup_cleanup,
        "move_no_replace",
        occupy_before_move,
    )

    # When: retention attempts its no-replace quarantine move.
    with pytest.raises(DocumentError) as captured:
        _ = retention._cleanup_backup(
            backup_root,
            backup,
            hashlib.sha256(payload).hexdigest(),
        )

    # Then: neither pathname is overwritten and recovery remains retryable.
    assert race_fired is True
    assert captured.value.retryable is True
    assert backup.read_bytes() == payload
    assert quarantine.read_bytes() == b"concurrent quarantine"
