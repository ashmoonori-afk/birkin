from __future__ import annotations

import errno
import hashlib
import os
from pathlib import Path

import pytest

from birkin.office import (
    export_displacement_restore,
    export_helper_retire,
    export_inode_publish,
    export_inode_publish_linux,
    export_named_publish,
    export_quarantine_retire,
)
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


def test_helper_retirement_preserves_link_added_during_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = tmp_path / "helper.bin"
    peer = tmp_path / "peer.bin"
    payload = b"authenticated helper"
    helper.write_bytes(payload)
    real_hash = export_helper_retire.hash_descriptor
    raced = False

    def add_link_during_hash(descriptor: int) -> str:
        nonlocal raced
        digest = real_hash(descriptor)
        os.link(helper, peer)
        raced = True
        return digest

    monkeypatch.setattr(
        export_helper_retire,
        "hash_descriptor",
        add_link_during_hash,
    )

    retired = retire_authenticated_file(
        helper,
        hashlib.sha256(payload).hexdigest(),
    )

    assert retired is True
    assert raced is True
    assert not helper.exists()
    assert peer.read_bytes() == payload


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX descriptor-relative quarantine race",
)
def test_quarantine_retirement_never_unlinks_swapped_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = tmp_path / "helper.bin"
    helper.write_bytes(b"authenticated helper")
    descriptor = os.open(helper, os.O_RDWR)
    metadata = os.fstat(descriptor)
    expected = metadata.st_dev, metadata.st_ino
    real_stat = export_quarantine_retire.os.stat
    swapped = False

    def swap_after_stat(
        path: str | bytes | int | os.PathLike[str] | os.PathLike[bytes],
        *args,
        **kwargs,
    ):
        nonlocal swapped
        result = real_stat(path, *args, **kwargs)
        directory = kwargs.get("dir_fd")
        if (
            not swapped
            and directory is not None
            and str(path).startswith("retired-")
        ):
            swapped = True
            os.rename(
                path,
                "saved-authenticated",
                src_dir_fd=directory,
                dst_dir_fd=directory,
            )
            replacement = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=directory,
            )
            try:
                _ = os.write(replacement, b"unrelated")
            finally:
                os.close(replacement)
        return result

    monkeypatch.setattr(
        export_quarantine_retire.os,
        "stat",
        swap_after_stat,
    )
    try:
        export_quarantine_retire.retire_bound_path(
            helper,
            descriptor,
            expected,
        )
    finally:
        os.close(descriptor)

    quarantine = tmp_path / ".birkin-retire"
    assert swapped is True
    assert (
        quarantine / "saved-authenticated"
    ).read_bytes() == b"authenticated helper"
    unrelated = tuple(quarantine.glob("retired-*"))
    assert len(unrelated) == 1
    assert unrelated[0].read_bytes() == b"unrelated"


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX hard-link quarantine race",
)
def test_quarantine_retirement_preserves_link_added_after_move(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = tmp_path / "helper.bin"
    peer = tmp_path / "peer.bin"
    payload = b"authenticated helper"
    helper.write_bytes(payload)
    move = export_quarantine_retire.move_no_replace_between
    linked = False

    def link_after_move(
        source_directory: int,
        source_name: str,
        destination_directory: int,
        destination_name: str,
    ) -> None:
        nonlocal linked
        move(
            source_directory,
            source_name,
            destination_directory,
            destination_name,
        )
        os.link(
            destination_name,
            peer,
            src_dir_fd=destination_directory,
        )
        linked = True

    monkeypatch.setattr(
        export_quarantine_retire,
        "move_no_replace_between",
        link_after_move,
    )

    retired = retire_authenticated_file(
        helper,
        hashlib.sha256(payload).hexdigest(),
    )

    assert retired is True
    assert linked is True
    assert not helper.exists()
    assert peer.read_bytes() == payload
    quarantined = tuple((tmp_path / ".birkin-retire").iterdir())
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == payload


def test_displacement_restore_moves_original_inode_without_copying(
    tmp_path: Path,
) -> None:
    # Given: one authenticated displacement checkpoint.
    checkpoint = tmp_path / "checkpoint.txt"
    destination = tmp_path / "destination.txt"
    payload = b"original destination"
    checkpoint.write_bytes(payload)
    identity = regular_file_identity(checkpoint)

    # When: restoration moves the original inode back no-replace.
    export_displacement_restore.restore_displaced(
        checkpoint,
        destination,
        hashlib.sha256(payload).hexdigest(),
    )

    # Then: no copy or destructive retirement touches caller bytes.
    assert not checkpoint.exists()
    assert destination.read_bytes() == payload
    assert regular_file_identity(destination) == identity


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

    # Then: recovery preserves both caller and checkpoint bytes.
    assert destination.read_bytes() == payload
    assert checkpoint.read_bytes() == payload


def test_darwin_clone_capability_error_uses_named_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_bytes(b"validated")
    called = False

    def unsupported_clone(descriptor: int, target: Path) -> None:
        del descriptor
        raise OSError(errno.ENOTSUP, "unsupported", target)

    def named_fallback(descriptor: int, target: Path) -> None:
        nonlocal called
        called = True
        os.lseek(descriptor, 0, os.SEEK_SET)
        target.write_bytes(os.read(descriptor, 64))

    monkeypatch.setattr(export_inode_publish.sys, "platform", "darwin")
    monkeypatch.setattr(export_inode_publish, "_clone_darwin", unsupported_clone)
    monkeypatch.setattr(
        export_inode_publish,
        "publish_named_copy",
        named_fallback,
    )

    descriptor = os.open(source, os.O_RDONLY)
    try:
        _ = export_inode_publish.publish_open_file(descriptor, destination)
    finally:
        os.close(descriptor)

    assert called is True
    assert destination.read_bytes() == b"validated"


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX O_TMPFILE capability path",
)
def test_linux_tmpfile_capability_error_uses_named_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_bytes(b"validated")
    called = False
    real_open = os.open

    def unsupported_tmpfile(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
    ) -> int:
        if flags & 0x400000:
            raise OSError(errno.ENOTSUP, "unsupported", path)
        return real_open(path, flags, mode)

    def named_fallback(descriptor: int, target: Path) -> None:
        nonlocal called
        called = True
        export_named_publish.publish_named_copy(descriptor, target)

    monkeypatch.setattr(
        export_inode_publish_linux.os,
        "O_TMPFILE",
        0x400000,
        raising=False,
    )
    monkeypatch.setattr(export_inode_publish_linux.os, "open", unsupported_tmpfile)
    monkeypatch.setattr(
        export_inode_publish_linux,
        "publish_named_copy",
        named_fallback,
    )

    descriptor = os.open(source, os.O_RDONLY)
    try:
        export_inode_publish_linux.publish_linux_copy(
            descriptor,
            destination,
        )
    finally:
        os.close(descriptor)

    assert called is True
    assert destination.read_bytes() == b"validated"
    assert regular_file_identity(destination) != regular_file_identity(source)


def test_named_fallback_never_replaces_occupied_destination(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_bytes(b"validated")
    destination.write_bytes(b"concurrent")
    descriptor = os.open(source, os.O_RDONLY)
    try:
        with pytest.raises(FileExistsError):
            export_named_publish.publish_named_copy(
                descriptor,
                destination,
            )
    finally:
        os.close(descriptor)

    assert destination.read_bytes() == b"concurrent"
    assert not tuple(tmp_path.glob(".destination.txt.birkin-publish"))
    quarantine = tmp_path / ".birkin-retire"
    if os.name == "nt":
        assert not quarantine.exists()
    else:
        quarantined = tuple(quarantine.iterdir())
        assert len(quarantined) == 1
        assert quarantined[0].read_bytes() == b""


@pytest.mark.parametrize("boundary", ["copy", "fsync"])
def test_named_fallback_failure_does_not_poison_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_bytes(b"validated")
    copy = export_named_publish.copy_descriptor
    sync = export_named_publish.os.fsync
    failed = False

    def fail_once(source_descriptor: int, destination_descriptor: int) -> None:
        nonlocal failed
        if boundary == "copy" and not failed:
            failed = True
            raise OSError(errno.EIO, "injected copy failure")
        copy(source_descriptor, destination_descriptor)

    def fail_sync_once(descriptor: int) -> None:
        nonlocal failed
        if boundary == "fsync" and not failed:
            failed = True
            raise OSError(errno.EIO, "injected fsync failure")
        sync(descriptor)

    monkeypatch.setattr(
        export_named_publish,
        "copy_descriptor",
        fail_once,
    )
    monkeypatch.setattr(export_named_publish.os, "fsync", fail_sync_once)

    descriptor = os.open(source, os.O_RDONLY)
    try:
        with pytest.raises(OSError, match=f"injected {boundary} failure"):
            export_named_publish.publish_named_copy(
                descriptor,
                destination,
            )
        export_named_publish.publish_named_copy(
            descriptor,
            destination,
        )
    finally:
        os.close(descriptor)

    assert failed is True
    assert destination.read_bytes() == b"validated"
