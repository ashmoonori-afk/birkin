"""Tests for Telegram adapter."""

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
from birkin.gateway.platforms.telegram_adapter import TelegramAdapter
from birkin.gateway.platforms.telegram_schemas import (
    Message,
    Update,
)
from birkin.memory.wiki import WikiMemory


@pytest.fixture
def adapter():
    """Create a Telegram adapter instance."""
    return TelegramAdapter(bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")


class TestTelegramAdapter:
    """Tests for TelegramAdapter class."""

    def test_format_session_key(self, adapter: TelegramAdapter) -> None:
        """Test session key generation from user ID."""
        key = adapter.format_session_key(user_id=987654321)
        assert key == "telegram_987654321"

    def test_parse_update_valid(self, adapter: TelegramAdapter) -> None:
        """Test parsing a valid Telegram update."""
        data = {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "date": 1234567890,
                "chat": {"id": 123, "type": "private"},
                "from": {
                    "id": 456,
                    "is_bot": False,
                    "first_name": "Test",
                    "username": "testuser",
                },
                "text": "Hello",
            },
        }
        update = adapter.parse_update(data)
        assert update is not None
        assert update.update_id == 1
        assert update.message is not None
        assert update.message.text == "Hello"
        assert update.message.from_user.id == 456

    def test_parse_update_invalid(self, adapter: TelegramAdapter) -> None:
        """Test parsing invalid update data."""
        data = {"invalid": "data"}
        update = adapter.parse_update(data)
        assert update is None

    def test_extract_message_valid(self, adapter: TelegramAdapter) -> None:
        """Test extracting message info from update."""
        message_data = {
            "message_id": 1,
            "date": 1234567890,
            "chat": {"id": 123, "type": "private"},
            "from": {
                "id": 456,
                "is_bot": False,
                "first_name": "Test",
                "username": "testuser",
            },
            "text": "Hello Birkin",
        }
        update = Update(
            update_id=1,
            message=Message(**message_data),
        )
        msg_info = adapter.extract_message(update)

        assert msg_info is not None
        assert msg_info["user_id"] == 456
        assert msg_info["chat_id"] == 123
        assert msg_info["text"] == "Hello Birkin"
        assert msg_info["message_id"] == 1
        assert msg_info["username"] == "testuser"

    def test_extract_message_no_text(self, adapter: TelegramAdapter) -> None:
        """Test extracting from message without text (e.g., photo)."""
        message_data = {
            "message_id": 1,
            "date": 1234567890,
            "chat": {"id": 123, "type": "private"},
            "from": {
                "id": 456,
                "is_bot": False,
                "first_name": "Test",
            },
            "text": None,  # No text content
        }
        update = Update(
            update_id=1,
            message=Message(**message_data),
        )
        msg_info = adapter.extract_message(update)
        assert msg_info is None

    def test_extract_message_no_message(self, adapter: TelegramAdapter) -> None:
        """Test extracting from update with no message."""
        update = Update(update_id=1, message=None)
        msg_info = adapter.extract_message(update)
        assert msg_info is None

    def test_api_endpoint(self, adapter: TelegramAdapter) -> None:
        """Test API endpoint URL construction."""
        expected = "https://api.telegram.org/bot123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
        assert adapter.api_endpoint == expected

    def test_verify_secret_correct(self) -> None:
        """Test verify_secret returns True for matching values."""
        assert TelegramAdapter.verify_secret("my-secret-token", "my-secret-token") is True

    def test_verify_secret_wrong(self) -> None:
        """Test verify_secret returns False for mismatched values."""
        assert TelegramAdapter.verify_secret("wrong-token", "my-secret-token") is False

    def test_verify_secret_empty(self) -> None:
        """Test verify_secret returns False for empty header value."""
        assert TelegramAdapter.verify_secret("", "my-secret-token") is False


# --- Webhook secret verification integration tests ----------------------------

_BOT_TOKEN = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"

_VALID_UPDATE = {
    "update_id": 1,
    "message": {
        "message_id": 1,
        "date": 1234567890,
        "chat": {"id": 123, "type": "private"},
        "from": {
            "id": 456,
            "is_bot": False,
            "first_name": "Test",
            "username": "testuser",
        },
        "text": "Hello",
    },
}


_AUTH_TOKEN = "test-auth-token"


@pytest.fixture()
def webhook_client(tmp_path, monkeypatch):
    """Client with TELEGRAM_BOT_TOKEN and BIRKIN_AUTH_TOKEN set."""
    import birkin.gateway.config as cfg_mod

    db_file = tmp_path / "test_sessions.db"
    set_session_store(SessionStore(db_path=db_file))

    wiki_dir = tmp_path / "wiki_memory"
    wiki = WikiMemory(root=wiki_dir)
    wiki.init()
    set_wiki_memory(wiki)

    # Isolate config file per test to avoid cross-test contamination
    monkeypatch.setattr(cfg_mod, "_CONFIG_PATH", tmp_path / "birkin_config.json")

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", _BOT_TOKEN)
    monkeypatch.setenv("BIRKIN_AUTH_TOKEN", _AUTH_TOKEN)
    reset_telegram_adapter()

    app = create_app()
    client = TestClient(app)
    yield client

    reset_telegram_adapter()
    reset_wiki_memory()
    reset_session_store()


def _set_webhook_secret(secret: str | None) -> None:
    """Helper: write config with the given webhook secret."""
    from birkin.gateway.config import load_config, save_config

    config = load_config()
    config["telegram_webhook_secret"] = secret
    save_config(config)


class TestWebhookSecretVerification:
    """Integration tests for X-Telegram-Bot-Api-Secret-Token verification."""

    def _auth_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        """Build headers with auth bearer token and optional extras."""
        headers = {"Authorization": f"Bearer {_AUTH_TOKEN}"}
        if extra:
            headers.update(extra)
        return headers

    def test_correct_secret_header(self, webhook_client: TestClient) -> None:
        """Webhook with correct secret header returns 200."""
        from unittest.mock import AsyncMock, MagicMock, patch

        secret = "test-secret-value"
        _set_webhook_secret(secret)

        mock_adapter = MagicMock()
        mock_adapter.parse_update.return_value = MagicMock()
        mock_adapter.extract_message.return_value = {
            "chat_id": 123,
            "user_id": 456,
            "text": "Hello",
            "message_id": 1,
        }
        mock_adapter.format_session_key.return_value = "tg_456"
        mock_adapter.send_message = AsyncMock()

        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch_message = AsyncMock(return_value="mocked reply")

        with (
            patch(
                "birkin.gateway.routers.webhooks.get_dispatcher",
                return_value=mock_dispatcher,
            ),
            patch(
                "birkin.gateway.routers.webhooks.get_telegram_adapter",
                return_value=mock_adapter,
            ),
        ):
            resp = webhook_client.post(
                f"/api/webhooks/telegram/{_BOT_TOKEN}",
                json=_VALID_UPDATE,
                headers=self._auth_headers({"X-Telegram-Bot-Api-Secret-Token": secret}),
            )
        # Should pass secret check and token check
        assert resp.status_code != 403
        assert resp.status_code == 200

    def test_wrong_secret_header(self, webhook_client: TestClient) -> None:
        """Webhook with wrong secret header returns 403."""
        _set_webhook_secret("correct-secret")

        resp = webhook_client.post(
            f"/api/webhooks/telegram/{_BOT_TOKEN}",
            json=_VALID_UPDATE,
            headers=self._auth_headers({"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"}),
        )
        assert resp.status_code == 403

    def test_missing_secret_header_when_configured(self, webhook_client: TestClient) -> None:
        """Webhook with missing secret header when secret is configured returns 403."""
        _set_webhook_secret("configured-secret")

        resp = webhook_client.post(
            f"/api/webhooks/telegram/{_BOT_TOKEN}",
            json=_VALID_UPDATE,
            headers=self._auth_headers(),
        )
        assert resp.status_code == 403

    def test_no_secret_in_config_legacy(self, webhook_client: TestClient) -> None:
        """When no secret in config (legacy), bot_token path check still works."""
        from unittest.mock import AsyncMock, MagicMock, patch

        _set_webhook_secret(None)

        mock_adapter = MagicMock()
        mock_adapter.parse_update.return_value = MagicMock()
        mock_adapter.extract_message.return_value = {
            "chat_id": 123,
            "user_id": 456,
            "text": "Hello",
            "message_id": 1,
        }
        mock_adapter.format_session_key.return_value = "tg_456"
        mock_adapter.send_message = AsyncMock()

        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch_message = AsyncMock(return_value="mocked reply")

        with (
            patch(
                "birkin.gateway.routers.webhooks.get_dispatcher",
                return_value=mock_dispatcher,
            ),
            patch(
                "birkin.gateway.routers.webhooks.get_telegram_adapter",
                return_value=mock_adapter,
            ),
        ):
            # Correct bot token should pass (not 401 or 403)
            resp = webhook_client.post(
                f"/api/webhooks/telegram/{_BOT_TOKEN}",
                json=_VALID_UPDATE,
                headers=self._auth_headers(),
            )
        assert resp.status_code != 401
        assert resp.status_code != 403
        assert resp.status_code == 200

    def test_no_secret_in_config_wrong_token(self, webhook_client: TestClient) -> None:
        """When no secret in config, wrong bot_token still returns 401."""
        _set_webhook_secret(None)

        resp = webhook_client.post(
            "/api/webhooks/telegram/wrong-token",
            json=_VALID_UPDATE,
            headers=self._auth_headers(),
        )
        assert resp.status_code == 401
