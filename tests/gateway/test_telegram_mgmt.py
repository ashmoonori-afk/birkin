"""Tests for the Telegram management API routes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from birkin.core.session import SessionStore
from birkin.gateway.app import create_app
from birkin.gateway.deps import (
    reset_session_store,
    reset_telegram_adapter,
    reset_wiki_memory,
    set_session_store,
    set_wiki_memory,
)
from birkin.memory.wiki import WikiMemory


@pytest.fixture(autouse=True)
def _clean_deps(tmp_path, monkeypatch):
    """Inject fresh deps and ensure no TELEGRAM_BOT_TOKEN by default."""
    db_file = tmp_path / "test_sessions.db"
    set_session_store(SessionStore(db_path=db_file))

    wiki_dir = tmp_path / "wiki_memory"
    wiki = WikiMemory(root=wiki_dir)
    wiki.init()
    set_wiki_memory(wiki)

    # Remove token so the "no token" tests work correctly
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    reset_telegram_adapter()

    yield

    reset_telegram_adapter()
    reset_wiki_memory()
    reset_session_store()


@pytest.fixture()
def client(_clean_deps):
    app = create_app()
    return TestClient(app)


class TestTelegramStatus:
    def test_status_no_token(self, client: TestClient):
        """When TELEGRAM_BOT_TOKEN is not set, return configured=false."""
        resp = client.get("/api/telegram/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["configured"] is False
        assert body["bot_info"] is None


class TestTelegramPolling:
    def test_start_polling_no_token(self, client: TestClient):
        """When TELEGRAM_BOT_TOKEN is not set, polling/start returns 400."""
        resp = client.post("/api/telegram/polling/start")
        assert resp.status_code == 400


class TestTelegramHealth:
    def test_telegram_health_endpoint(self, client: TestClient):
        """Health endpoint returns ok and polling_active fields."""
        resp = client.get("/api/telegram/health")
        assert resp.status_code == 200
        body = resp.json()
        assert "ok" in body
        assert "polling_active" in body
        assert body["ok"] is True
        assert body["polling_active"] is False


class TestTelegramSendTest:
    def test_send_test_no_token(self, client: TestClient):
        """When TELEGRAM_BOT_TOKEN is not set, send-test returns 400."""
        resp = client.post(
            "/api/telegram/send-test",
            json={"chat_id": "12345"},
        )
        assert resp.status_code == 400

    def test_send_test_missing_chat_id(self, client: TestClient):
        """When chat_id is missing, returns 400 regardless of token."""
        resp = client.post("/api/telegram/send-test", json={})
        assert resp.status_code == 400
        assert "chat_id" in resp.json()["detail"]
