from __future__ import annotations

import contextlib
import hashlib
import os
import stat
from pathlib import Path

import pytest

from birkin.office.errors import DocumentError, DocumentErrorCode
from birkin.office.service_workspace import DocumentWorkspace


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode semantics")
def test_workspace_directories_are_private_under_permissive_umask(
    tmp_path: Path,
) -> None:
    home = tmp_path / "office"
    with contextlib.ExitStack() as cleanup:
        _ = cleanup.callback(os.umask, os.umask(0))
        workspace = DocumentWorkspace(home)

    source = home / "source.txt"
    _ = source.write_text("confidential", encoding="utf-8")
    output = workspace.output_path("result.txt", ".txt")
    _ = workspace.atomic_publish(output, lambda _target: None)
    reference = {
        "uri": str(source),
        "content_hash": hashlib.sha256(source.read_bytes()).hexdigest(),
    }

    with workspace.artifact_snapshot(reference) as snapshot:
        assert stat.S_IMODE(snapshot.stat().st_mode) == 0o400

    for directory in (workspace.home, home / "artifacts", workspace.drafts):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode semantics")
def test_workspace_tightens_preexisting_broad_directories(tmp_path: Path) -> None:
    home = tmp_path / "office"
    artifacts = home / "artifacts"
    drafts = artifacts / "drafts"
    drafts.mkdir(parents=True)
    for directory in (home, artifacts, drafts):
        directory.chmod(0o755)

    workspace = DocumentWorkspace(home)

    for directory in (workspace.home, artifacts, workspace.drafts):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlink semantics")
def test_workspace_refuses_artifacts_symlink_without_chmodding_target(
    tmp_path: Path,
) -> None:
    home = tmp_path / "office"
    target = tmp_path / "external-artifacts"
    home.mkdir()
    target.mkdir(mode=0o755)
    target.chmod(0o755)
    (home / "artifacts").symlink_to(target, target_is_directory=True)

    with pytest.raises(DocumentError) as caught:
        _ = DocumentWorkspace(home)

    assert caught.value.code is DocumentErrorCode.PERMISSION_DENIED
    assert stat.S_IMODE(target.stat().st_mode) == 0o755


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlink semantics")
def test_workspace_refuses_drafts_symlink_without_chmodding_target(
    tmp_path: Path,
) -> None:
    home = tmp_path / "office"
    artifacts = home / "artifacts"
    target = tmp_path / "external-drafts"
    artifacts.mkdir(parents=True)
    target.mkdir(mode=0o755)
    target.chmod(0o755)
    (artifacts / "drafts").symlink_to(target, target_is_directory=True)

    with pytest.raises(DocumentError) as caught:
        _ = DocumentWorkspace(home)

    assert caught.value.code is DocumentErrorCode.PERMISSION_DENIED
    assert stat.S_IMODE(target.stat().st_mode) == 0o755
