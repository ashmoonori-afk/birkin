from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast

import pytest


class _Artifact(Protocol):
    ref: str
    digest: str
    byte_length: int


class _ArtifactStore(Protocol):
    def put_screenshot(self, content: bytes) -> _Artifact: ...

    def resolve(self, ref: str) -> bytes: ...

    def purge(self) -> tuple[str, ...]: ...

    def close(self) -> None: ...


class _LifecycleModule(Protocol):
    ArtifactQuotaExceeded: type[Exception]

    def browser_artifact_store(
        self,
        root: Path,
        *,
        clock: Callable[[], float],
        retention_seconds: int,
        max_records: int,
        max_bytes: int,
    ) -> _ArtifactStore: ...


def _module() -> _LifecycleModule:
    module: ModuleType = importlib.import_module(
        "birkin.browser_aside_lifecycle"
    )
    return cast(_LifecycleModule, cast(object, module))


def test_purge_retention_and_quota_are_deterministic(
    tmp_path: Path,
) -> None:
    now = [100.0]
    module = _module()
    store = module.browser_artifact_store(
        tmp_path,
        clock=lambda: now[0],
        retention_seconds=60,
        max_records=2,
        max_bytes=8,
    )
    first = store.put_screenshot(b"aaaa")
    for _ in range(10):
        duplicate = store.put_screenshot(b"aaaa")
        assert duplicate.ref == first.ref
    second = store.put_screenshot(b"bbbb")
    assert store.resolve(first.ref) == b"aaaa"
    assert store.resolve(second.ref) == b"bbbb"
    with pytest.raises(module.ArtifactQuotaExceeded):
        _ = store.put_screenshot(b"c")

    now[0] = 161.0
    assert set(store.purge()) == {first.ref, second.ref}
    with pytest.raises(KeyError):
        _ = store.resolve(first.ref)
    assert not tuple(tmp_path.rglob("*.tmp"))
    store.close()
