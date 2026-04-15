"""Tests for Telegram adapter."""

from __future__ import annotations

import pytest

from birkin.gateway.platforms.telegram_adapter import TelegramAdapter
from birkin.gateway.platforms.telegram_schemas import (
    Message,
    Update,
)


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
