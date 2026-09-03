"""_write_json survives a transient Windows sharing violation on os.replace."""

from __future__ import annotations

import os

import pytest

from birkin import store


def test_replace_retries_a_transient_permission_error(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: os.replace fails twice with a sharing violation, then succeeds.
    real_replace = os.replace
    calls: list[int] = []

    def _flaky(src, dst):  # noqa: ANN001, ANN202 - mirrors os.replace
        calls.append(1)
        if len(calls) <= 2:
            raise PermissionError(13, "sharing violation")
        return real_replace(src, dst)

    monkeypatch.setattr(store.os, "replace", _flaky)
    monkeypatch.setattr(store.time, "sleep", lambda _seconds: None)
    path = tmp_path / "state.json"

    # When: a JSON state file is written.
    store._write_json(path, {"value": 1})

    # Then: the write lands after three attempts.
    assert len(calls) == 3
    assert path.read_text(encoding="utf-8").strip().endswith("}")


def test_replace_reraises_a_persistent_permission_error(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: os.replace always fails with a sharing violation.
    calls: list[int] = []

    def _always(src, dst):  # noqa: ANN001, ANN202 - mirrors os.replace
        calls.append(1)
        raise PermissionError(13, "sharing violation")

    monkeypatch.setattr(store.os, "replace", _always)
    monkeypatch.setattr(store.time, "sleep", lambda _seconds: None)
    path = tmp_path / "state.json"

    # When/Then: the caller still sees the failure, after a bounded retry.
    with pytest.raises(PermissionError):
        store._write_json(path, {"value": 1})
    assert len(calls) == 10
    assert not list(tmp_path.glob("*.tmp"))
