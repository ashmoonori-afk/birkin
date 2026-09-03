"""Ledger storage failures must never look like valid empty audit state."""

from __future__ import annotations

import sqlite3
import warnings

import pytest

from birkin import ledger


def test_write_permission_failure_returns_typed_diagnostic(monkeypatch):
    def deny_connection():
        raise PermissionError("ledger directory is read-only")

    monkeypatch.setattr(ledger, "_connect", deny_connection)

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = ledger.event("run:chat", "must remain observable")

    assert result.ok is False
    assert isinstance(result.error, ledger.LedgerError)
    assert result.error.operation == "write"
    assert result.error.code == "permission_denied"


def test_json_conversion_failure_returns_typed_diagnostic():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = ledger.event("run:chat", data={"invalid": object()})

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "encoding"


def test_programmer_errors_are_not_converted_to_ledger_failures(monkeypatch):
    def broken_connection():
        raise AssertionError("programmer bug")

    monkeypatch.setattr(ledger, "_connect", broken_connection)

    with pytest.raises(AssertionError, match="programmer bug"):
        ledger.event("run:chat")
    with pytest.raises(AssertionError, match="programmer bug"):
        ledger.usage()
    with pytest.raises(AssertionError, match="programmer bug"):
        ledger.recent()


def test_corrupt_ledger_query_raises_typed_error(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    (tmp_path / "ledger.db").write_bytes(b"not a sqlite database")

    with pytest.raises(ledger.LedgerError) as caught:
        ledger.recent()

    assert caught.value.operation == "query_recent"
    assert caught.value.code == "corrupt"


def test_incompatible_schema_usage_raises_instead_of_zero(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    with sqlite3.connect(tmp_path / "ledger.db") as connection:
        connection.execute("CREATE TABLE events (id INTEGER PRIMARY KEY)")

    with pytest.raises(ledger.LedgerError) as caught:
        ledger.usage()

    assert caught.value.operation == "query_usage"
    assert caught.value.code == "schema"


def test_normal_writes_and_queries_keep_their_values(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))

    assert ledger.usage() == 0
    assert ledger.recent() == []

    result = ledger.event("run:chat", "recorded", tokens=17)
    rows = ledger.recent()

    assert result == ledger.LedgerWriteResult(ok=True)
    assert ledger.usage() == 17
    assert rows == [
        {
            "ts": rows[0]["ts"],
            "kind": "run:chat",
            "summary": "recorded",
            "tokens": 17,
        }
    ]
