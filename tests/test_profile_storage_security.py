from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from birkin.profile_actions import ProfileActions
from birkin.rolefiles import ProfileEdit, ProfileStore
from tests.symlink_support import create_symlink


def _store(home: Path) -> ProfileStore:
    return ProfileStore(home, {})


def _create_directory_link(link: Path, target: Path) -> None:
    if os.name != "nt":
        create_symlink(link, target, target_is_directory=True)
        return
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        pytest.skip("Windows junction creation unavailable")


def test_snapshot_refuses_symlinked_profile_root_without_reading_outside(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = "OUTSIDE-PROFILE-SENTINEL"
    (outside / "preferences.md").write_text(
        f"## Guidance\n- {sentinel}\n", encoding="utf-8"
    )
    (tmp_path / "home").mkdir()
    _create_directory_link(tmp_path / "home" / "profile", outside)

    with pytest.raises(OSError, match="symlink|reparse"):
        _store(tmp_path / "home").snapshot()


def test_apply_refuses_symlinked_profile_root_without_writing_outside(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "preferences.md"
    target.write_text("OUTSIDE-UNCHANGED", encoding="utf-8")
    before = target.read_bytes()
    (tmp_path / "home").mkdir()
    _create_directory_link(tmp_path / "home" / "profile", outside)

    with pytest.raises(OSError, match="symlink|reparse"):
        _store(tmp_path / "home").apply(
            ProfileEdit("preferences", "add", content="must not escape")
        )

    assert target.read_bytes() == before


def test_snapshot_refuses_symlinked_profile_document_without_reading_target(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "home")
    store.bootstrap()
    outside = tmp_path / "outside.md"
    outside.write_text("## Guidance\n- OUTSIDE-SENTINEL\n", encoding="utf-8")
    document = store.root / "preferences.md"
    document.unlink()
    create_symlink(document, outside)

    with pytest.raises(OSError, match="symlink|reparse"):
        store.snapshot()


def test_apply_refuses_symlinked_profile_document_without_writing_target(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "home")
    store.bootstrap()
    outside = tmp_path / "outside.md"
    outside.write_text("OUTSIDE-UNCHANGED", encoding="utf-8")
    before = outside.read_bytes()
    document = store.root / "preferences.md"
    document.unlink()
    create_symlink(document, outside)

    with pytest.raises(OSError, match="symlink|reparse"):
        store.apply(ProfileEdit("preferences", "add", content="must not escape"))

    assert outside.read_bytes() == before


def test_pending_queue_refuses_reparse_root_read_and_write_escape(
    tmp_path: Path,
) -> None:
    actions = ProfileActions(_store(tmp_path / "home"), approval_required=True)
    shutil.rmtree(actions.store.root)
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "pending-v1.json"
    target.write_text('{"version": 1, "pending": []}\n', encoding="utf-8")
    before = target.read_bytes()
    _create_directory_link(actions.store.root, outside)

    with pytest.raises(OSError, match="symlink|reparse"):
        actions.pending()
    with pytest.raises(OSError, match="symlink|reparse"):
        actions.submit(
            ProfileEdit("preferences", "add", content="must not escape"),
            trusted=True,
            source="test",
        )

    assert target.read_bytes() == before


def test_pending_queue_refuses_symlink_read_and_write_escape(tmp_path: Path) -> None:
    actions = ProfileActions(_store(tmp_path / "home"), approval_required=True)
    outside = tmp_path / "outside.json"
    outside.write_text('{"version": 1, "pending": []}\n', encoding="utf-8")
    before = outside.read_bytes()
    create_symlink(actions.store.root / "pending-v1.json", outside)

    with pytest.raises(OSError, match="symlink|reparse"):
        actions.pending()
    with pytest.raises(OSError, match="symlink|reparse"):
        actions.submit(
            ProfileEdit("preferences", "add", content="must not escape"),
            trusted=True,
            source="test",
        )

    assert outside.read_bytes() == before


def test_profile_and_pending_storage_are_owner_only(tmp_path: Path) -> None:
    from tests.test_native_private_storage import assert_owner_only

    actions = ProfileActions(_store(tmp_path / "home"), approval_required=True)
    receipt = actions.submit(
        ProfileEdit("preferences", "add", content="tone: concise"),
        trusted=True,
        source="test",
    )
    assert receipt.status == "pending"

    assert_owner_only(actions.store.root, posix_mode=0o700)
    for name in ("mask.md", "preferences.md", "pending-v1.json"):
        assert_owner_only(actions.store.root / name, posix_mode=0o600)

    if os.name == "nt":
        # The ACL assertion above is the Windows evidence, not a chmod proxy.
        assert not (actions.store.root / "pending-v1.json").is_symlink()
