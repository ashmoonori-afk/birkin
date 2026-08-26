from __future__ import annotations

import os
import stat
import threading
from pathlib import Path

import pytest

from birkin.gateway.channels import capability_file
from birkin.gateway.channels import local_http
from birkin.native import private_storage
from tests.test_native_private_storage import assert_owner_only


def test_gateway_windows_read_hardens_before_use_without_fchmod(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability = tmp_path / "gateway_http_token"
    capability.write_text("complete-winner\n", encoding="utf-8")
    opened: list[Path] = []

    def open_hardened_handle(path: Path) -> int:
        opened.append(path)
        return os.open(path, os.O_RDONLY)

    def reject_fchmod(_descriptor: int, _mode: int) -> None:
        raise AssertionError(
            "Windows must not fchmod a read-only capability descriptor"
        )

    monkeypatch.setattr(
        capability_file,
        "_IS_WINDOWS",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        capability_file,
        "open_private_file_for_read",
        open_hardened_handle,
        raising=False,
    )
    monkeypatch.setattr(capability_file.os, "fchmod", reject_fchmod)

    assert capability_file._read_token(capability) == "complete-winner"
    assert opened == [capability]


def test_gateway_windows_read_consumes_hardened_handle_after_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability = tmp_path / "gateway_http_token"
    replacement = tmp_path / "replacement"
    capability.write_text("original-secret\n", encoding="utf-8")
    replacement.write_text("replacement-secret\n", encoding="utf-8")
    capability.chmod(0o666)
    replacement.chmod(0o666)
    real_read = os.read
    hardened_descriptors: set[int] = set()
    hardened_before_read: list[bool] = []
    consumed_modes: list[int] = []

    def open_hardened_handle(path: Path) -> int:
        descriptor = private_storage.open_private_file_for_read(path)
        assert_owner_only(path, posix_mode=0o600)
        hardened_descriptors.add(descriptor)
        os.replace(replacement, path)
        return descriptor

    def harden_replaced_path(path: Path) -> None:
        os.replace(replacement, path)
        private_storage.harden_private_file(path)

    def observe_read(descriptor: int, size: int) -> bytes:
        hardened_before_read.append(descriptor in hardened_descriptors)
        if os.name != "nt":
            consumed_modes.append(stat.S_IMODE(os.fstat(descriptor).st_mode))
        return real_read(descriptor, size)

    monkeypatch.setattr(
        capability_file,
        "open_private_file_for_read",
        open_hardened_handle,
        raising=False,
    )
    monkeypatch.setattr(capability_file, "_IS_WINDOWS", True)
    monkeypatch.setattr(
        capability_file,
        "harden_private_file",
        harden_replaced_path,
        raising=False,
    )
    monkeypatch.setattr(capability_file.os, "read", observe_read)

    assert capability_file._read_token(capability) == "original-secret"
    assert hardened_before_read == [True]
    if os.name != "nt":
        assert consumed_modes == [0o600]
    assert capability.read_text(encoding="utf-8") == "replacement-secret\n"
    assert stat.S_IMODE(capability.stat().st_mode) == 0o666


def test_gateway_capability_publication_is_atomic_under_concurrency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("BIRKIN_HOME", str(home))
    created = threading.Event()
    release = threading.Event()
    original_create_private_temp = private_storage.create_private_temp
    creator_results: list[tuple[str, Path]] = []
    creator_errors: list[RuntimeError] = []

    def delayed_private_temp(
        directory: Path,
        *,
        prefix: str,
    ) -> tuple[int, str]:
        descriptor, name = original_create_private_temp(
            directory,
            prefix=prefix,
        )
        if not created.is_set():
            created.set()
            assert release.wait(timeout=2)
        return descriptor, name

    monkeypatch.setattr(
        capability_file,
        "create_private_temp",
        delayed_private_temp,
        raising=False,
    )
    monkeypatch.setattr(
        capability_file,
        "_IS_WINDOWS",
        True,
        raising=False,
    )

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
    assert_owner_only(second_result[1], posix_mode=0o600)
    assert list(home.glob(".gateway_http_token.*.tmp")) == []


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
