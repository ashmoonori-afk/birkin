from __future__ import annotations

import os
import hashlib
from pathlib import Path

import pytest

from birkin.office import export_displacement_restore, export_inode_publish
from birkin.office.export_helper_retire import retire_authenticated_file
from birkin.office.export_io import regular_file_identity


@pytest.mark.skipif(os.name == "nt", reason="POSIX linkat fallback contract")
def test_descriptor_link_binds_destination_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one validated descriptor and a destination parent.
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    _ = source.write_text("validated", encoding="utf-8")
    calls: list[tuple[Path, str, int, bool]] = []

    def record_link(
        descriptor_path: Path,
        name: str,
        *,
        dst_dir_fd: int,
        follow_symlinks: bool,
    ) -> None:
        calls.append(
            (
                descriptor_path,
                name,
                os.fstat(dst_dir_fd).st_ino,
                follow_symlinks,
            )
        )

    monkeypatch.setattr(os, "link", record_link)

    # When: the non-Darwin descriptor-link fallback publishes it.
    with source.open("rb") as stream:
        descriptor_paths = {
            Path(f"/proc/self/fd/{stream.fileno()}"),
            Path(f"/dev/fd/{stream.fileno()}"),
        }
        export_inode_publish.link_descriptor(
            stream.fileno(),
            destination,
        )

    # Then: os.link must dispatch through linkat and the opened parent.
    assert len(calls) == 1
    descriptor_path, name, parent_inode, follows = calls[0]
    assert descriptor_path in descriptor_paths
    assert name == destination.name
    assert parent_inode == tmp_path.stat().st_ino
    assert follows is True


def test_helper_retirement_preserves_hard_linked_destination(
    tmp_path: Path,
) -> None:
    # Given: Linux/Windows publication linked staging and destination.
    staging = tmp_path / "staging.txt"
    destination = tmp_path / "destination.txt"
    payload = b"validated export"
    staging.write_bytes(payload)
    os.link(staging, destination)
    identity = regular_file_identity(destination)

    # When: cleanup considers the still-published helper.
    retired = retire_authenticated_file(
        staging,
        hashlib.sha256(payload).hexdigest(),
        expected_identity=identity,
        protected_identity=identity,
        required=False,
    )

    # Then: neither hard-link name loses the published bytes.
    assert retired is False
    assert staging.read_bytes() == payload
    assert destination.read_bytes() == payload


def test_displacement_restore_preserves_hard_linked_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: Linux/Windows restores a checkpoint with a hard link.
    checkpoint = tmp_path / "checkpoint.txt"
    destination = tmp_path / "destination.txt"
    payload = b"original destination"
    checkpoint.write_bytes(payload)

    def hard_link_restore(
        descriptor: int,
        target: Path,
    ) -> tuple[int, int]:
        del descriptor
        os.link(checkpoint, target)
        return regular_file_identity(target)

    monkeypatch.setattr(
        export_displacement_restore,
        "publish_open_file",
        hard_link_restore,
    )

    # When: restoration retires only non-aliased checkpoint storage.
    export_displacement_restore.restore_displaced(
        checkpoint,
        destination,
        hashlib.sha256(payload).hexdigest(),
    )

    # Then: both hard-link names retain the restored bytes.
    assert checkpoint.read_bytes() == payload
    assert destination.read_bytes() == payload


def test_displacement_restore_accepts_expected_recreated_destination(
    tmp_path: Path,
) -> None:
    # Given: a concurrent writer recreated the expected prior bytes.
    checkpoint = tmp_path / "checkpoint.txt"
    destination = tmp_path / "destination.txt"
    payload = b"original bytes"
    checkpoint.write_bytes(payload)
    destination.write_bytes(payload)

    # When: compensation observes the already-restored destination.
    export_displacement_restore.restore_displaced(
        checkpoint,
        destination,
        hashlib.sha256(payload).hexdigest(),
    )

    # Then: recovery remains typed and retires only the distinct checkpoint.
    assert destination.read_bytes() == payload
    assert checkpoint.read_bytes() == b""
