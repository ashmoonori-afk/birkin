from __future__ import annotations

import errno
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from birkin.native.jailed_import import (
    MAX_IMPORT_BYTES,
    MAX_JAIL_BYTES,
    JailedImportAuthority,
)
from birkin.workspace.contracts import ProtocolError


def _seed_owned_file(jail: Path, size: int, serial: int) -> Path:
    path = jail / f"import-{serial:032x}.bin"
    with path.open("wb") as stream:
        _ = stream.truncate(size)
    return path


def test_repeated_exact_file_limit_imports_cannot_exceed_aggregate_quota(
    tmp_path: Path,
) -> None:
    # Given: capacity for exactly one more maximum-sized import.
    source = tmp_path / "exact.bin"
    with source.open("wb") as stream:
        _ = stream.truncate(MAX_IMPORT_BYTES)
    authority = JailedImportAuthority(tmp_path / "jail")
    _ = _seed_owned_file(
        authority.jail,
        MAX_JAIL_BYTES - MAX_IMPORT_BYTES,
        serial=1,
    )

    # When: one exact-limit import fills the jail.
    _ = authority.import_file({"source_path": str(source)})

    # Then: another exact-limit import is refused.
    with pytest.raises(ProtocolError, match="aggregate byte limit"):
        _ = authority.import_file({"source_path": str(source)})


def test_concurrent_imports_cannot_oversubscribe_aggregate_quota(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: concurrent calls race for capacity that admits only one.
    source = tmp_path / "source.bin"
    _ = source.write_bytes(b"race")
    jail = tmp_path / "jail"
    first_authority = JailedImportAuthority(jail)
    second_authority = JailedImportAuthority(jail)
    _ = _seed_owned_file(
        jail,
        MAX_JAIL_BYTES - len(b"race"),
        serial=1,
    )
    contender_count = 2
    source_stat_barrier = threading.Barrier(contender_count)
    original_fstat = os.fstat

    def synchronize_source_stats(fd: int) -> os.stat_result:
        result = original_fstat(fd)
        if result.st_ino == source.stat().st_ino:
            _ = source_stat_barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(os, "fstat", synchronize_source_stats)

    # When: all calls pass source inspection together.
    with ThreadPoolExecutor(max_workers=contender_count) as executor:
        futures = [
            executor.submit(authority.import_file, {"source_path": str(source)})
            for authority in (first_authority, second_authority)
        ]
        outcomes: list[str] = []
        for future in futures:
            try:
                _ = future.result(timeout=10)
            except ProtocolError:
                outcomes.append("refused")
            else:
                outcomes.append("imported")

    # Then: atomic admission permits exactly one.
    assert outcomes.count("imported") == 1
    assert outcomes.count("refused") == contender_count - 1


def test_failed_write_releases_quota_reservation_and_removes_partial_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: the remaining capacity is reserved by one import.
    source = tmp_path / "source.bin"
    payload = b"write failure"
    _ = source.write_bytes(payload)
    authority = JailedImportAuthority(tmp_path / "jail")
    filler = _seed_owned_file(
        authority.jail,
        MAX_JAIL_BYTES - len(payload),
        serial=1,
    )
    original_write = os.write

    def fail_write(_fd: int, _data: memoryview) -> int:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(os, "write", fail_write)

    # When: copying fails after aggregate admission.
    with pytest.raises(OSError, match="No space left on device"):
        _ = authority.import_file({"source_path": str(source)})

    # Then: no partial remains and the released capacity can be reused.
    assert list(authority.jail.iterdir()) == [filler]
    monkeypatch.setattr(os, "write", original_write)
    result = authority.import_file({"source_path": str(source)})
    receipt = result["receipt"]
    assert isinstance(receipt, dict)
    assert receipt["byte_count"] == len(payload)


def test_source_growth_releases_quota_reservation_and_removes_partial_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: a one-byte source reserves the jail's final byte.
    source = tmp_path / "source.bin"
    _ = source.write_bytes(b"x")
    authority = JailedImportAuthority(tmp_path / "jail")
    filler = _seed_owned_file(authority.jail, MAX_JAIL_BYTES - 1, serial=1)
    original_read = os.read
    grew = False

    def grow_during_read(fd: int, size: int) -> bytes:
        nonlocal grew
        if not grew:
            grew = True
            return b"xx"
        return original_read(fd, size)

    monkeypatch.setattr(os, "read", grow_during_read)

    # When: the source produces more bytes than it reserved.
    with pytest.raises(ProtocolError, match="changed during import"):
        _ = authority.import_file({"source_path": str(source)})

    # Then: rollback leaves only the filler and capacity is reusable.
    assert list(authority.jail.iterdir()) == [filler]
    monkeypatch.setattr(os, "read", original_read)
    result = authority.import_file({"source_path": str(source)})
    receipt = result["receipt"]
    assert isinstance(receipt, dict)
    assert receipt["byte_count"] == 1


def test_import_succeeds_at_exact_aggregate_limit(tmp_path: Path) -> None:
    # Given: aggregate capacity exactly equal to the source size.
    source = tmp_path / "source.bin"
    payload = b"exact aggregate"
    _ = source.write_bytes(payload)
    authority = JailedImportAuthority(tmp_path / "jail")
    _ = _seed_owned_file(
        authority.jail,
        MAX_JAIL_BYTES - len(payload),
        serial=1,
    )

    # When: the source is imported.
    result = authority.import_file({"source_path": str(source)})

    # Then: the aggregate reaches, but does not exceed, the canonical limit.
    receipt = result["receipt"]
    assert isinstance(receipt, dict)
    assert receipt["byte_count"] == len(payload)
    assert sum(path.stat().st_size for path in authority.jail.iterdir()) == MAX_JAIL_BYTES


def test_over_limit_refusal_is_bounded_typed_and_leaves_jail_unchanged(
    tmp_path: Path,
) -> None:
    # Given: an owned regular file leaves insufficient aggregate capacity.
    source = tmp_path / "source.bin"
    _ = source.write_bytes(b"too large")
    authority = JailedImportAuthority(tmp_path / "jail")
    _ = _seed_owned_file(authority.jail, MAX_JAIL_BYTES - 1, serial=1)
    before = [(path.name, path.stat().st_size) for path in authority.jail.iterdir()]

    # When: aggregate admission refuses the source.
    with pytest.raises(ProtocolError) as refusal:
        _ = authority.import_file({"source_path": str(source)})

    # Then: the error is bounded and the jail has not changed.
    assert type(refusal.value) is ProtocolError
    assert str(refusal.value) == "import jail exceeds aggregate byte limit"
    assert len(str(refusal.value)) < 128
    assert [(path.name, path.stat().st_size) for path in authority.jail.iterdir()] == before


def test_stale_canonical_partial_file_consumes_aggregate_quota(tmp_path: Path) -> None:
    # Given: a stale canonical partial occupies all but fewer bytes than the source.
    source = tmp_path / "source.bin"
    payload = b"charged"
    _ = source.write_bytes(payload)
    authority = JailedImportAuthority(tmp_path / "jail")
    stale_partial = authority.jail / f".partial-{'a' * 32}"
    with stale_partial.open("wb") as stream:
        _ = stream.truncate(MAX_JAIL_BYTES - len(payload) + 1)

    # When: the source is admitted against the shared aggregate quota.
    with pytest.raises(ProtocolError, match="aggregate byte limit"):
        _ = authority.import_file({"source_path": str(source)})

    # Then: the stale partial remains and its bytes block oversubscription.
    assert stale_partial.stat().st_size == MAX_JAIL_BYTES - len(payload) + 1


def test_aggregate_accounting_does_not_follow_or_delete_partial_symlinks_or_dotfiles(
    tmp_path: Path,
) -> None:
    # Given: a canonical-looking partial symlink and an unrelated dotfile in the jail.
    external = tmp_path / "external.bin"
    with external.open("wb") as stream:
        _ = stream.truncate(MAX_JAIL_BYTES)
    source = tmp_path / "source.bin"
    _ = source.write_bytes(b"safe")
    authority = JailedImportAuthority(tmp_path / "jail")
    partial_symlink = authority.jail / f".partial-{'f' * 32}"
    unrelated_dotfile = authority.jail / ".keep"
    _ = partial_symlink.symlink_to(external)
    _ = unrelated_dotfile.write_bytes(b"unrelated")

    # When: a regular source is imported.
    result = authority.import_file({"source_path": str(source)})

    # Then: neither non-owned entry is charged, followed, or deleted.
    receipt = result["receipt"]
    assert isinstance(receipt, dict)
    assert receipt["byte_count"] == len(b"safe")
    assert partial_symlink.is_symlink()
    assert unrelated_dotfile.read_bytes() == b"unrelated"


def test_aggregate_accounting_ignores_owned_name_symlinks(tmp_path: Path) -> None:
    # Given: a large external file is linked under an owned-looking jail name.
    external = tmp_path / "external.bin"
    with external.open("wb") as stream:
        _ = stream.truncate(MAX_JAIL_BYTES)
    source = tmp_path / "source.bin"
    _ = source.write_bytes(b"safe")
    authority = JailedImportAuthority(tmp_path / "jail")
    _ = (authority.jail / f"import-{'f' * 32}.bin").symlink_to(external)

    # When: a regular source is imported.
    result = authority.import_file({"source_path": str(source)})

    # Then: accounting does not follow or charge the symlink target.
    receipt = result["receipt"]
    assert isinstance(receipt, dict)
    assert receipt["byte_count"] == len(b"safe")
