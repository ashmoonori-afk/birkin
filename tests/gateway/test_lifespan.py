"""Tests for the FastAPI lifespan (startup/shutdown) behaviour."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from birkin.core.session import SessionStore
from birkin.gateway.app import create_app
from birkin.gateway.deps import reset_session_store, set_session_store


@pytest.fixture(autouse=True)
def _clean_store(tmp_path):
    """Inject a fresh isolated session store for each test."""
    db_file = tmp_path / "test_sessions.db"
    set_session_store(SessionStore(db_path=db_file))
    yield
    reset_session_store()


class TestLifespan:
    """Verify the lifespan context manager wires startup and shutdown."""

    def test_client_request_and_clean_shutdown(self):
        """TestClient enters/exits lifespan without errors."""
        app = create_app()
        with TestClient(app) as client:
            resp = client.get("/api/health")
            assert resp.status_code == 200
        # If we reach here, shutdown completed without raising.

    def test_close_all_closes_connections(self, tmp_path):
        """SessionStore.close_all() actually closes every tracked connection."""
        db_file = tmp_path / "closeall_test.db"
        store = SessionStore(db_path=db_file)

        # Force a connection to be created via a read operation.
        store.create(title="test-session")

        # Grab the raw connection before closing.
        conn = store._get_connection()
        assert isinstance(conn, sqlite3.Connection)

        store.close_all()

        # After close_all the connection should be unusable.
        with pytest.raises(Exception):  # noqa: B017
            conn.execute("SELECT 1")

    def test_close_all_is_idempotent(self, tmp_path):
        """Calling close_all() twice must not raise."""
        db_file = tmp_path / "idempotent_test.db"
        store = SessionStore(db_path=db_file)
        store.create(title="x")

        store.close_all()
        store.close_all()  # second call should be safe
