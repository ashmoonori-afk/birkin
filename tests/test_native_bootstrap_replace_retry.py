"""write_record survives a transient Windows sharing violation on os.replace."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from birkin import store
from birkin.native import bootstrap


def test_write_record_retries_a_transient_permission_error(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a client holds endpoint.json open, so os.replace fails twice.
    real_replace = os.replace
    calls: list[int] = []

    def _flaky(src, dst):  # noqa: ANN001, ANN202 - mirrors os.replace
        calls.append(1)
        if len(calls) <= 2:
            raise PermissionError(13, "sharing violation")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", _flaky)
    monkeypatch.setattr(store.time, "sleep", lambda _seconds: None)
    path = tmp_path / "endpoint.json"
    record = bootstrap.new_record(
        datetime.now(timezone.utc),
        timedelta(minutes=5),
    )

    # When: the bootstrap record is rewritten.
    bootstrap.write_record(path, record)

    # Then: the rewrite lands after three attempts and leaves no temp file.
    assert len(calls) == 3
    assert bootstrap.read_record(path).secret == record.secret
    assert [entry.name for entry in tmp_path.iterdir()] == ["endpoint.json"]
