"""Connection ownership for SQLite-backed runtime journals."""

from __future__ import annotations

import sqlite3

from birkin import delivery, ledger
from birkin.moirai import journal


class _TrackedConnection(sqlite3.Connection):
    was_closed = False

    def close(self) -> None:
        self.was_closed = True
        super().close()


def test_sqlite_connections_close_after_each_operation(tmp_path, monkeypatch):
    # Given: all three SQLite modules use real tracked connections in isolation.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    real_connect = sqlite3.connect
    connections: list[_TrackedConnection] = []

    def tracked_connect(*args, **kwargs):
        kwargs["factory"] = _TrackedConnection
        connection = real_connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", tracked_connect)

    # When: each module completes one public write operation.
    journal.start_run(
        "run-1", name="qa", script_path="workflow.toml",
        script_sha256="sha", args={}, bindings={})
    delivery.record("http", "chat-1", "hello")
    ledger.event("qa", "connection lifecycle")

    # Then: transaction completion also releases every connection it created.
    assert len(connections) == 3
    assert all(connection.was_closed for connection in connections)
