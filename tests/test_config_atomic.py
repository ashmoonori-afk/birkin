"""Security contract for atomic config.json persistence."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from birkin import config, private_storage
from tests.test_native_private_storage import assert_owner_only

_POSIX_ONLY = pytest.mark.skipif(os.name != "posix", reason="POSIX mode contract")
_WINDOWS_ONLY = pytest.mark.skipif(os.name != "nt", reason="Windows DACL contract")


def _temporary_siblings(path: Path) -> list[Path]:
    return list(path.parent.glob(f".{path.name}.*"))


def test_save_config_round_trips_without_temporary_residue() -> None:
    # Given: an isolated Birkin home.
    # When: a non-default override is persisted.
    path = config.save_config({**config.DEFAULT_CONFIG, "model": "sonnet"})

    # Then: the override round-trips and no private temporary remains.
    assert json.loads(path.read_text(encoding="utf-8"))["model"] == "sonnet"
    assert _temporary_siblings(path) == []


def test_save_config_failure_keeps_original_intact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an existing valid config and a failing atomic replacement.
    path = config.save_config({**config.DEFAULT_CONFIG, "model": "good"})
    original = path.read_bytes()

    def reject_replace(_source: Path, _destination: Path) -> None:
        raise OSError("sentinel replacement failure")

    monkeypatch.setattr(private_storage.os, "replace", reject_replace)

    # When: replacement fails.
    with pytest.raises(OSError, match="sentinel replacement failure"):
        _ = config.save_config({**config.DEFAULT_CONFIG, "model": "bad"})

    # Then: the prior bytes remain and the private temporary is removed.
    assert path.read_bytes() == original
    assert _temporary_siblings(path) == []


def test_save_config_hardening_failure_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an existing config containing a dummy value.
    path = config.save_config(
        {**config.DEFAULT_CONFIG, "api_key": "stored-dummy-value"},
    )
    original = path.read_bytes()

    def reject_hardening(_path: Path) -> None:
        raise OSError("sentinel hardening failure")

    monkeypatch.setattr(private_storage, "harden_private_file", reject_hardening)

    # When: owner-only hardening cannot be applied.
    with pytest.raises(OSError, match="sentinel hardening failure") as captured:
        _ = config.save_config(
            {**config.DEFAULT_CONFIG, "api_key": "replacement-dummy-value"},
        )

    # Then: persistence fails closed without replacing or disclosing prior bytes.
    assert path.read_bytes() == original
    assert "stored-dummy-value" not in str(captured.value)
    assert "replacement-dummy-value" not in str(captured.value)
    assert _temporary_siblings(path) == []


def test_save_config_uses_private_temporary_siblings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: observation of atomic replacement sources.
    sources: list[Path] = []
    real_replace = private_storage.os.replace

    def record_replace(source: Path, destination: Path) -> None:
        sources.append(Path(source))
        real_replace(source, destination)

    monkeypatch.setattr(private_storage.os, "replace", record_replace)

    # When: two configs are persisted.
    first = config.save_config({**config.DEFAULT_CONFIG, "model": "first"})
    _ = config.save_config({**config.DEFAULT_CONFIG, "model": "second"})

    # Then: unique helper-named private siblings were used and removed.
    assert len(set(sources)) == 2
    assert all(source.parent == first.parent for source in sources)
    assert all(source.name.startswith(".config.json.") for source in sources)
    assert _temporary_siblings(first) == []


@_POSIX_ONLY
def test_save_config_applies_owner_only_posix_modes() -> None:
    # Given: an isolated Birkin home.
    # When: a config is persisted.
    path = config.save_config({**config.DEFAULT_CONFIG, "model": "safe"})

    # Then: both the home and config are owner-only.
    assert_owner_only(path.parent, posix_mode=0o700)
    assert_owner_only(path, posix_mode=0o600)


@_WINDOWS_ONLY
def test_save_config_applies_handle_bound_owner_only_windows_dacl() -> None:
    # Given: an isolated Birkin home.
    # When: a config is persisted.
    path = config.save_config({**config.DEFAULT_CONFIG, "model": "safe"})

    # Then: the final config has a protected owner-only DACL.
    assert_owner_only(path, posix_mode=0o600)
