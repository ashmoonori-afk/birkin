"""The --all version sync rewrites derived artifacts without touching prose."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from scripts.native.sync_version import (
    BRIDGE_INPUTS,
    DOCUMENTS,
    UV_LOCK,
    set_documented_version,
    set_locked_version,
    set_project_digests,
)

FUTURE = "9.9.9"


def _changed_lines(before: str, after: str) -> list[str]:
    return [
        line
        for line, previous in zip(after.splitlines(), before.splitlines(), strict=True)
        if line != previous
    ]


def test_lock_rewrite_touches_only_the_editable_birkin_entry(tmp_path: Path) -> None:
    # Given a copy of the real lock file.
    copy = tmp_path / UV_LOCK.name
    _ = shutil.copy2(UV_LOCK, copy)
    before = copy.read_text(encoding="utf-8")

    # When the sync restates a new manifest version in it.
    after = set_locked_version(before, FUTURE)
    _ = copy.write_text(after, encoding="utf-8")

    # Then exactly the birkin package version line moved.
    assert _changed_lines(before, after) == [f'version = "{FUTURE}"']
    assert f'name = "birkin"\nversion = "{FUTURE}"' in copy.read_text(encoding="utf-8")


def test_documentation_rewrite_touches_only_version_mentions(tmp_path: Path) -> None:
    for source in DOCUMENTS:
        # Given a copy of a published document.
        copy = tmp_path / source.name
        _ = shutil.copy2(source, copy)
        before = copy.read_text(encoding="utf-8")

        # When the sync rewrites its Birkin version mentions.
        after = set_documented_version(before, FUTURE)
        _ = copy.write_text(after, encoding="utf-8")

        # Then every changed line is a version mention and nothing else moved.
        changed = _changed_lines(before, after)
        assert changed, source
        assert all(f"`{FUTURE}`" in line for line in changed), source
        assert f"`{FUTURE}`" in copy.read_text(encoding="utf-8"), source


def test_helper_input_digests_follow_the_files_they_pin(tmp_path: Path) -> None:
    # Given a copy of the helper input descriptor and freshly written inputs.
    copy = tmp_path / BRIDGE_INPUTS.name
    _ = shutil.copy2(BRIDGE_INPUTS, copy)
    manifest = b'[project]\nversion = "9.9.9"\n'
    lock = b'name = "birkin"\r\nversion = "9.9.9"\r\n'

    # When the sync re-pins the descriptor to those bytes.
    after = set_project_digests(
        copy.read_text(encoding="utf-8"), pyproject=manifest, lock=lock
    )
    _ = copy.write_text(after, encoding="utf-8")

    # Then both digests match the checkout-normalized bytes the builder hashes.
    descriptor = copy.read_text(encoding="utf-8")
    expected_manifest = hashlib.sha256(manifest).hexdigest()
    expected_lock = hashlib.sha256(lock.replace(b"\r\n", b"\n")).hexdigest()
    assert f'"pyproject_sha256": "{expected_manifest}"' in descriptor
    assert f'"uv_lock_sha256": "{expected_lock}"' in descriptor
