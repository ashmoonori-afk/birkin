from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

import pytest

from birkin.computer_use.artifacts import (
    ArtifactError,
    ArtifactScope,
    ArtifactStore,
)


def test_raw_capture_is_content_addressed_and_metadata_is_bounded(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path, max_bytes=64, max_annotations=2)
    payload = b"\x89PNG\r\nfixture"
    scope = ArtifactScope(
        session_id="session-a",
        app_ref="app-opaque",
        window_ref="window-opaque",
        snapshot_generation=3,
    )

    artifact = store.put_capture(
        payload,
        media_type="image/png",
        width=320,
        height=200,
        scope=scope,
        isolated=True,
        annotations=["button", "email@example.com", "discarded"],
    )

    digest = hashlib.sha256(payload).hexdigest()
    assert artifact.ref == f"sha256:{digest}"
    assert artifact.byte_size == len(payload)
    assert artifact.scope == scope
    assert artifact.annotations == ("button", "[REDACTED_EMAIL]")
    assert artifact.raw_bytes is None
    assert store.path_for(artifact).read_bytes() == payload
    if os.name == "posix":
        assert stat.S_IMODE(store.path_for(artifact).stat().st_mode) == 0o600
        assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700


def test_capture_rejects_unisolated_or_oversized_pixels(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path, max_bytes=8)
    scope = ArtifactScope(
        session_id="session-a",
        app_ref="app-opaque",
        window_ref="window-opaque",
        snapshot_generation=1,
    )

    with pytest.raises(ArtifactError) as isolation:
        store.put_capture(
            b"image",
            media_type="image/png",
            width=10,
            height=10,
            scope=scope,
            isolated=False,
        )
    assert isolation.value.code == "capture_isolation_unavailable"

    with pytest.raises(ArtifactError) as size:
        store.put_capture(
            b"too-many-bytes",
            media_type="image/png",
            width=10,
            height=10,
            scope=scope,
            isolated=True,
        )
    assert size.value.code == "resource_limit"


def test_artifact_retention_is_bounded(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path, max_artifacts=2)
    scope = ArtifactScope(
        session_id="session-a",
        app_ref="app-opaque",
        window_ref="window-opaque",
        snapshot_generation=1,
    )

    for payload in (b"first", b"second", b"third"):
        store.put_capture(
            payload,
            media_type="image/png",
            width=10,
            height=10,
            scope=scope,
            isolated=True,
        )

    assert len(list((tmp_path / "sha256").glob("*/*"))) == 2
