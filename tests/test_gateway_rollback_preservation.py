from __future__ import annotations

import os
import queue
import stat
import threading
from pathlib import Path

import pytest

from birkin.gateway.channels import local_http
from tests.test_native_private_storage import assert_owner_only


def test_gateway_ambiguous_post_link_failure_preserves_complete_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("BIRKIN_HOME", str(home))
    original_link = local_http.os.link

    def fail_after_link(
        source: os.PathLike[str] | str,
        destination: os.PathLike[str] | str,
    ) -> None:
        original_link(source, destination)
        raise OSError("synthetic ambiguous publication failure")

    monkeypatch.setattr(local_http.os, "link", fail_after_link)

    with pytest.raises(
        OSError,
        match="synthetic ambiguous publication failure",
    ):
        local_http._load_or_create_token()

    assert list(home.glob(".gateway_http_token.*.tmp")) == []
    capability = home / "gateway_http_token"
    assert len(capability.read_text(encoding="utf-8").strip()) >= 32
    assert_owner_only(capability, posix_mode=0o600)


@pytest.mark.skipif(
    os.name == "nt",
    reason="directory fsync rollback is a POSIX durability contract",
)
def test_gateway_rollback_never_unlinks_replaced_winner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("BIRKIN_HOME", str(home))
    capability = home / "gateway_http_token"
    replacement = home / "replacement"
    replacement.write_text("replacement-winner\n", encoding="utf-8")
    replacement.chmod(0o600)
    original_fsync = local_http.os.fsync
    original_stat = Path.stat
    identity_observed = threading.Event()
    replacement_ready = threading.Event()
    outcomes: queue.Queue[str] = queue.Queue()

    def fail_directory_fsync(descriptor: int) -> None:
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("synthetic directory fsync failure")
        original_fsync(descriptor)

    def observe_identity(
        path: Path,
        *,
        follow_symlinks: bool = True,
    ) -> os.stat_result:
        metadata = original_stat(
            path,
            follow_symlinks=follow_symlinks,
        )
        if path == capability and not identity_observed.is_set():
            identity_observed.set()
            outcomes.put("identity-observed")
            assert replacement_ready.wait(timeout=5)
        return metadata

    monkeypatch.setattr(local_http.os, "fsync", fail_directory_fsync)
    monkeypatch.setattr(Path, "stat", observe_identity)

    def create() -> None:
        try:
            local_http._load_or_create_token()
        except OSError:
            outcomes.put("completed")

    creator = threading.Thread(target=create)
    creator.start()
    first = outcomes.get(timeout=5)
    if first == "identity-observed":
        os.replace(replacement, capability)
        replacement_ready.set()
        assert outcomes.get(timeout=5) == "completed"
    creator.join(timeout=5)
    monkeypatch.setattr(Path, "stat", original_stat)

    assert not creator.is_alive()
    assert first == "completed"
    assert not identity_observed.is_set()
    assert capability.exists()
    assert capability.stat().st_mode & 0o777 == 0o600
