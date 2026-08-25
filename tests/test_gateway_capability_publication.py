from __future__ import annotations

import os
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
