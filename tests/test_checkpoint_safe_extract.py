"""Security contract for checkpoint archive extraction without tar filters."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from birkin import checkpoints


@pytest.mark.parametrize(
    ("name", "member_type", "linkname"),
    [
        ("/absolute.txt", tarfile.REGTYPE, ""),
        ("../outside.txt", tarfile.REGTYPE, ""),
        ("inside/link", tarfile.SYMTYPE, "../../outside.txt"),
        ("inside/link", tarfile.LNKTYPE, "../outside.txt"),
        ("device", tarfile.CHRTYPE, ""),
    ],
)
def test_safe_extract_rejects_malicious_members_when_filter_is_unsupported(
    tmp_path: Path,
    name: str,
    member_type: bytes,
    linkname: str,
) -> None:
    # Given
    payload = io.BytesIO()
    member = tarfile.TarInfo(name)
    member.type = member_type
    member.linkname = linkname
    member.size = len(b"owned")
    with tarfile.open(fileobj=payload, mode="w") as archive:
        archive.addfile(member, io.BytesIO(b"owned"))
    payload.seek(0)
    target = tmp_path / "target"
    target.mkdir()

    # When
    with tarfile.open(fileobj=payload, mode="r:") as archive:
        with pytest.raises(checkpoints.CheckpointError):
            checkpoints._safe_extract(archive, target)

    # Then
    assert not (tmp_path / "outside.txt").exists()


def test_safe_extract_preserves_regular_file_and_directory_metadata(
    tmp_path: Path,
) -> None:
    # Given
    payload = io.BytesIO()
    directory = tarfile.TarInfo("bin")
    directory.type = tarfile.DIRTYPE
    directory.mode = 0o755
    directory.mtime = 1_700_000_000
    executable = tarfile.TarInfo("bin/run.sh")
    executable.mode = 0o755
    executable.mtime = 1_700_000_001
    executable.size = len(b"#!/bin/sh\n")
    with tarfile.open(fileobj=payload, mode="w") as archive:
        archive.addfile(directory)
        archive.addfile(executable, io.BytesIO(b"#!/bin/sh\n"))
    payload.seek(0)
    target = tmp_path / "target"
    target.mkdir()

    # When
    with tarfile.open(fileobj=payload, mode="r:") as archive:
        checkpoints._safe_extract(archive, target)

    # Then
    assert (target / "bin").is_dir()
    assert (target / "bin" / "run.sh").read_bytes() == b"#!/bin/sh\n"
    assert int((target / "bin").stat().st_mtime) == directory.mtime
    assert int((target / "bin" / "run.sh").stat().st_mtime) == executable.mtime
