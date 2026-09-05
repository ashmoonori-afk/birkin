from __future__ import annotations

import hashlib
import os
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from birkin.office.export_helper_retire import retire_authenticated_file


pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX retirement quarantine")


def _retire(root: Path, name: str, payload: bytes) -> None:
    source = root / name
    _ = source.write_bytes(payload)
    assert retire_authenticated_file(source, hashlib.sha256(payload).hexdigest())


def test_retired_payloads_are_owner_only_and_sweep_bounds_items_bytes_and_age(tmp_path: Path) -> None:
    from birkin.office.retirement_sweep import sweep_retirement_quarantine

    for index in range(4):
        _retire(tmp_path, f"secret-{index}", bytes([65 + index]) * 8)
    quarantine = tmp_path / ".birkin-retire"
    files = list(quarantine.glob("retired-*"))
    assert files
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in files)
    old = (datetime.now(timezone.utc) - timedelta(days=10)).timestamp()
    os.utime(files[0], (old, old), follow_symlinks=False)

    receipt = sweep_retirement_quarantine(tmp_path, max_age_seconds=60,
                                           max_items=2, max_bytes=12)

    payloads = [p for p in quarantine.glob("retired-*") if p.stat().st_size]
    assert len(payloads) <= 2
    assert sum(p.stat().st_size for p in payloads) <= 12
    assert files[0].stat().st_size == 0
    assert receipt["payload_items"] <= 2
    assert receipt["payload_bytes"] <= 12
    assert receipt["secure_erasure"] is False
    assert len(receipt["diagnostics"]) <= 8


def test_sweep_never_follows_symlink_or_truncates_swapped_or_tampered_object(tmp_path: Path) -> None:
    from birkin.office import retirement_sweep

    _retire(tmp_path, "secret", b"authenticated")
    quarantine = tmp_path / ".birkin-retire"
    retired = next(quarantine.glob("retired-*"))
    victim = tmp_path / "victim"
    _ = victim.write_bytes(b"VICTIM")
    link = quarantine / (retired.name + "-link")
    link.symlink_to(victim)
    _ = retired.write_bytes(b"tampered")

    receipt = retirement_sweep.sweep_retirement_quarantine(
        tmp_path, max_age_seconds=0, max_items=0, max_bytes=0)

    assert victim.read_bytes() == b"VICTIM"
    assert retired.read_bytes() == b"tampered"
    assert receipt["tampered"] >= 1
    assert receipt["unsafe"] >= 1
