"""Tests for security self-check endpoint."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from birkin.gateway.app import create_app


class TestSecurityCheck:
    def test_returns_all_checks(self):
        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)
        res = client.get("/api/security/check")
        assert res.status_code == 200
        data = res.json()
        assert "score" in data
        assert "checks" in data
        assert "grade" in data
        assert len(data["checks"]) >= 5

    def test_all_checks_have_required_fields(self):
        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)
        data = client.get("/api/security/check").json()
        for check in data["checks"]:
            assert "name" in check
            assert "status" in check
            assert check["status"] in ("pass", "warn", "fail")
            assert "detail" in check

    def test_shell_sandbox_off_fails(self):
        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)
        with patch.dict("os.environ", {"BIRKIN_SHELL_SANDBOX": "off"}):
            data = client.get("/api/security/check").json()
        shell = next(c for c in data["checks"] if c["name"] == "Shell Sandbox")
        assert shell["status"] == "fail"

    def test_sanitization_check_passes(self):
        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)
        data = client.get("/api/security/check").json()
        san = next(c for c in data["checks"] if c["name"] == "Memory Sanitization")
        assert san["status"] == "pass"
