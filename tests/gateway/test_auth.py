"""Tests for Bearer token authentication middleware."""

from __future__ import annotations

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


@pytest.fixture()
def client(_clean_store):
    app = create_app()
    return TestClient(app)


# ── Helpers ──────────────────────────────────────────────────────────


def _set_token(monkeypatch: pytest.MonkeyPatch, token: str) -> None:
    monkeypatch.setenv("BIRKIN_AUTH_TOKEN", token)


def _clear_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BIRKIN_AUTH_TOKEN", raising=False)


# ── Tests ────────────────────────────────────────────────────────────


class TestNoTokenDevMode:
    """When BIRKIN_AUTH_TOKEN is not set, all requests pass through (dev mode)."""

    def test_no_token_allows_request(self, client, monkeypatch):
        _clear_token(monkeypatch)
        res = client.get("/api/sessions")
        assert res.status_code == 200


class TestTokenRequired:
    """When BIRKIN_AUTH_TOKEN is set, requests without valid credentials are rejected."""

    def test_no_header_returns_401(self, client, monkeypatch):
        _set_token(monkeypatch, "super-secret-token")
        res = client.get("/api/sessions")
        assert res.status_code == 401

    def test_correct_bearer_header_returns_200(self, client, monkeypatch):
        _set_token(monkeypatch, "super-secret-token")
        res = client.get(
            "/api/sessions",
            headers={"Authorization": "Bearer super-secret-token"},
        )
        assert res.status_code == 200

    def test_wrong_bearer_header_returns_401(self, client, monkeypatch):
        _set_token(monkeypatch, "super-secret-token")
        res = client.get(
            "/api/sessions",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert res.status_code == 401

    def test_correct_cookie_returns_200(self, client, monkeypatch):
        _set_token(monkeypatch, "super-secret-token")
        client.cookies.set("birkin_session", "super-secret-token")
        res = client.get("/api/sessions")
        assert res.status_code == 200


class TestExemptPaths:
    """Exempt paths should always return 200 regardless of auth state."""

    def test_health_always_200(self, client, monkeypatch):
        _set_token(monkeypatch, "super-secret-token")
        res = client.get("/api/health")
        assert res.status_code == 200

    def test_auth_status_always_200(self, client, monkeypatch):
        _set_token(monkeypatch, "super-secret-token")
        res = client.get("/api/auth/status")
        assert res.status_code == 200

    def test_auth_bootstrap_always_reachable(self, client, monkeypatch):
        _set_token(monkeypatch, "super-secret-token")
        res = client.post(
            "/api/auth/bootstrap",
            json={"token": "wrong"},
        )
        # 401 from the endpoint logic, NOT from middleware
        assert res.status_code == 401


class TestBootstrapEndpoint:
    """POST /api/auth/bootstrap should set an HttpOnly cookie on success."""

    def test_bootstrap_sets_cookie(self, client, monkeypatch):
        _set_token(monkeypatch, "my-token")
        res = client.post(
            "/api/auth/bootstrap",
            json={"token": "my-token"},
        )
        assert res.status_code == 200
        assert res.json() == {"ok": True}
        assert "birkin_session" in res.cookies

    def test_bootstrap_wrong_token(self, client, monkeypatch):
        _set_token(monkeypatch, "my-token")
        res = client.post(
            "/api/auth/bootstrap",
            json={"token": "bad-token"},
        )
        assert res.status_code == 401

    def test_bootstrap_no_token_env(self, client, monkeypatch):
        _clear_token(monkeypatch)
        res = client.post(
            "/api/auth/bootstrap",
            json={"token": "anything"},
        )
        assert res.status_code == 200
        assert res.json() == {"ok": True}


class TestAuthStatus:
    """GET /api/auth/status reports correct auth state."""

    def test_no_token_env(self, client, monkeypatch):
        _clear_token(monkeypatch)
        res = client.get("/api/auth/status")
        data = res.json()
        assert data["auth_required"] is False
        assert data["authenticated"] is True

    def test_token_env_not_authenticated(self, client, monkeypatch):
        _set_token(monkeypatch, "secret")
        res = client.get("/api/auth/status")
        data = res.json()
        assert data["auth_required"] is True
        assert data["authenticated"] is False

    def test_token_env_authenticated_via_header(self, client, monkeypatch):
        _set_token(monkeypatch, "secret")
        res = client.get(
            "/api/auth/status",
            headers={"Authorization": "Bearer secret"},
        )
        data = res.json()
        assert data["auth_required"] is True
        assert data["authenticated"] is True
