"""Tests for the onboarding-action endpoint."""

from __future__ import annotations

from unittest.mock import patch

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


class TestOnboardingAction:
    def test_onboarding_action_no_telegram(self, client: TestClient):
        """Without TELEGRAM_BOT_TOKEN the endpoint returns telegram_configured: false."""
        with patch.dict("os.environ", {}, clear=False):
            # Ensure the env var is absent
            import os

            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            resp = client.post("/api/chat/onboarding-action")

        assert resp.status_code == 200
        body = resp.json()
        assert body["telegram_configured"] is False
        assert body["workflow_created"] is False

    def test_onboarding_action_creates_workflow(self, client: TestClient, tmp_path):
        """With TELEGRAM_BOT_TOKEN set, the endpoint creates the workflow."""
        wf_file = tmp_path / "birkin_workflows.json"
        with (
            patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "123:ABC"}, clear=False),
            patch("birkin.gateway.workflows._WORKFLOWS_PATH", wf_file),
            patch("birkin.triggers.storage.TriggerStore") as mock_store_cls,
        ):
            mock_store = mock_store_cls.return_value
            resp = client.post("/api/chat/onboarding-action")

        assert resp.status_code == 200
        body = resp.json()
        assert body["telegram_configured"] is True
        assert body["workflow_created"] is True
        mock_store.save.assert_called_once()
        mock_store.close.assert_called_once()

    def test_onboarding_action_idempotent(self, client: TestClient, tmp_path):
        """Second call does not create a duplicate workflow."""
        wf_file = tmp_path / "birkin_workflows.json"
        with (
            patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "123:ABC"}, clear=False),
            patch("birkin.gateway.workflows._WORKFLOWS_PATH", wf_file),
            patch("birkin.triggers.storage.TriggerStore") as mock_store_cls,
        ):
            # First call creates the workflow
            resp1 = client.post("/api/chat/onboarding-action")
            assert resp1.json()["workflow_created"] is True

            # Second call should be idempotent — workflow already exists
            resp2 = client.post("/api/chat/onboarding-action")
            assert resp2.status_code == 200
            body2 = resp2.json()
            assert body2["telegram_configured"] is True
            assert body2["workflow_created"] is True

            # TriggerStore.save should only be called once (first call)
            assert mock_store_cls.return_value.save.call_count == 1
