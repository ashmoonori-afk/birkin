"""Tests for the Birkin gateway API routes."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from birkin.core.session import SessionStore
from birkin.gateway.app import create_app
from birkin.gateway.deps import reset_session_store, set_session_store
from tests.fakes import FakeProvider


@pytest.fixture(autouse=True)
def _clean_store(tmp_path):
    """Inject a fresh isolated session store for each test."""
    db_file = tmp_path / "test_sessions.db"
    set_session_store(SessionStore(db_path=db_file))
    yield
    reset_session_store()


@pytest.fixture()
def client(_clean_store):
    app = create_app()
    return TestClient(app)


# ── Health ──


class TestHealth:
    def test_health_returns_ok(self, client: TestClient):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["version"] == "0.1.0"


# ── Sessions CRUD ──


class TestSessions:
    def test_list_empty(self, client: TestClient):
        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_session(self, client: TestClient):
        resp = client.post("/api/sessions")
        assert resp.status_code == 201
        body = resp.json()
        assert "id" in body
        assert body["message_count"] == 0

    def test_get_session(self, client: TestClient):
        create_resp = client.post("/api/sessions")
        sid = create_resp.json()["id"]

        resp = client.get(f"/api/sessions/{sid}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == sid
        assert body["messages"] == []

    def test_get_session_not_found(self, client: TestClient):
        resp = client.get("/api/sessions/nonexistent")
        assert resp.status_code == 404

    def test_delete_session(self, client: TestClient):
        create_resp = client.post("/api/sessions")
        sid = create_resp.json()["id"]

        resp = client.delete(f"/api/sessions/{sid}")
        assert resp.status_code == 204

    def test_list_after_create(self, client: TestClient):
        client.post("/api/sessions")
        client.post("/api/sessions")
        resp = client.get("/api/sessions")
        assert len(resp.json()) == 2


# ── Chat ──


class TestChat:
    @patch("birkin.gateway.routes.create_provider")
    @patch("birkin.gateway.routes.load_tools", return_value=[])
    def test_chat_creates_session(self, _mock_tools, mock_provider, client: TestClient):
        mock_provider.return_value = FakeProvider(reply="hi there")

        resp = client.post("/api/chat", json={"message": "hello"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["reply"] == "hi there"
        assert "session_id" in body

    @patch("birkin.gateway.routes.create_provider")
    @patch("birkin.gateway.routes.load_tools", return_value=[])
    def test_chat_continues_session(self, _mock_tools, mock_provider, client: TestClient):
        mock_provider.return_value = FakeProvider(reply="first")

        r1 = client.post("/api/chat", json={"message": "one"})
        sid = r1.json()["session_id"]

        mock_provider.return_value = FakeProvider(reply="second")
        r2 = client.post("/api/chat", json={"message": "two", "session_id": sid})
        assert r2.status_code == 200
        assert r2.json()["session_id"] == sid

        # Verify session has accumulated messages
        detail = client.get(f"/api/sessions/{sid}")
        assert len(detail.json()["messages"]) == 4  # 2 user + 2 assistant

    @patch("birkin.gateway.routes.create_provider")
    @patch("birkin.gateway.routes.load_tools", return_value=[])
    def test_chat_not_found_session(self, _mock_tools, mock_provider, client: TestClient):
        mock_provider.return_value = FakeProvider()
        resp = client.post("/api/chat", json={"message": "hi", "session_id": "bad_id"})
        assert resp.status_code == 404

    def test_chat_empty_message_rejected(self, client: TestClient):
        resp = client.post("/api/chat", json={"message": ""})
        assert resp.status_code == 422
