from __future__ import annotations

import os
import stat
import threading
from pathlib import Path

import pytest

from birkin.gateway.channels import local_http


def test_gateway_capability_publication_is_atomic_under_concurrency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    created = threading.Event()
    release = threading.Event()
    original_open = local_http.os.open
    creator_results: list[tuple[str, Path]] = []
    creator_errors: list[RuntimeError] = []

    def delayed_open(
        path: os.PathLike[str] | str,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if (
            flags & os.O_CREAT
            and flags & os.O_EXCL
            and flags & os.O_WRONLY
            and not created.is_set()
        ):
            created.set()
            assert release.wait(timeout=2)
        return descriptor

    monkeypatch.setattr(local_http.os, "open", delayed_open)

    def create_first() -> None:
        try:
            creator_results.append(local_http._load_or_create_token())
        except RuntimeError as exc:
            creator_errors.append(exc)

    creator = threading.Thread(target=create_first)
    creator.start()
    assert created.wait(timeout=2)
    second_result: tuple[str, Path] | None = None
    second_error: RuntimeError | None = None
    try:
        second_result = local_http._load_or_create_token()
    except RuntimeError as exc:
        second_error = exc
    finally:
        release.set()
        creator.join(timeout=2)

    assert not creator.is_alive()
    assert creator_errors == []
    assert second_error is None
    assert creator_results
    assert second_result is not None
    assert creator_results[0] == second_result
    assert len(second_result[0]) >= 32
    assert second_result[1].stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "failure",
    [
        "write",
        "file_fsync",
        "publish",
    ],
)
def test_gateway_capability_failure_removes_private_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("BIRKIN_HOME", str(home))
    original_write = local_http.os.write
    original_fsync = local_http.os.fsync
    original_link = local_http.os.link

    def injected_write(descriptor: int, payload: bytes | memoryview) -> int:
        if failure == "write":
            raise OSError("synthetic write failure")
        return original_write(descriptor, payload)

    def injected_fsync(descriptor: int) -> None:
        mode = os.fstat(descriptor).st_mode
        if failure == "file_fsync" and stat.S_ISREG(mode):
            raise OSError("synthetic file fsync failure")
        original_fsync(descriptor)

    def injected_link(
        source: os.PathLike[str] | str,
        destination: os.PathLike[str] | str,
    ) -> None:
        if failure == "publish":
            raise OSError("synthetic publication failure")
        original_link(source, destination)

    monkeypatch.setattr(local_http.os, "write", injected_write)
    monkeypatch.setattr(local_http.os, "fsync", injected_fsync)
    monkeypatch.setattr(local_http.os, "link", injected_link)

    with pytest.raises(OSError, match="synthetic"):
        local_http._load_or_create_token()

    assert list(home.glob(".gateway_http_token.*.tmp")) == []
    assert not (home / "gateway_http_token").exists()


@pytest.mark.skipif(
    os.name == "nt",
    reason="directory fsync is a POSIX durability contract",
)
def test_gateway_directory_fsync_failure_preserves_complete_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("BIRKIN_HOME", str(home))
    original_fsync = local_http.os.fsync

    def fail_directory_fsync(descriptor: int) -> None:
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("synthetic directory fsync failure")
        original_fsync(descriptor)

    monkeypatch.setattr(local_http.os, "fsync", fail_directory_fsync)

    with pytest.raises(OSError, match="synthetic directory fsync failure"):
        local_http._load_or_create_token()

    assert list(home.glob(".gateway_http_token.*.tmp")) == []
    capability = home / "gateway_http_token"
    assert len(capability.read_text(encoding="utf-8").strip()) >= 32
    assert capability.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(
    os.name == "nt",
    reason="directory fsync is a POSIX durability contract",
)
def test_gateway_capability_fsyncs_file_and_parent_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    original_fsync = local_http.os.fsync
    synced_types: list[str] = []

    def record_fsync(descriptor: int) -> None:
        mode = os.fstat(descriptor).st_mode
        synced_types.append("directory" if stat.S_ISDIR(mode) else "file")
        original_fsync(descriptor)

    monkeypatch.setattr(local_http.os, "fsync", record_fsync)

    local_http._load_or_create_token()

    assert synced_types == ["file", "directory"]
