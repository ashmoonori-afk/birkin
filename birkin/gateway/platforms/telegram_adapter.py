"""Telegram Bot adapter for Birkin gateway."""

from __future__ import annotations

import hmac
import logging
import secrets
from datetime import UTC, datetime
from typing import Any, Optional

import httpx

from birkin.gateway.platforms.telegram_schemas import Update

logger = logging.getLogger(__name__)


class TelegramAdapter:
    """Adapter for Telegram Bot API integration."""

    def __init__(self, bot_token: str) -> None:
        """Initialize Telegram adapter with bot token.

        Args:
            bot_token: Telegram Bot API token (from BotFather).
        """
        self._bot_token = bot_token
        self.api_base = "https://api.telegram.org"
        self.client = httpx.AsyncClient(timeout=30.0)

    @property
    def api_endpoint(self) -> str:
        """Construct base API URL."""
        return f"{self.api_base}/bot{self._bot_token}"

    _MAX_MSG_LEN = 4096

    async def send_message(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: Optional[int] = None,
    ) -> dict[str, Any]:
        """Send a text message to a Telegram chat.

        Automatically splits messages exceeding Telegram's 4096-char limit.

        Args:
            chat_id: Telegram chat ID.
            text: Message text.
            reply_to_message_id: Optional message ID to reply to.

        Returns:
            API response dict (from the last chunk sent).

        Raises:
            httpx.HTTPError: If API call fails.
        """
        # Split long messages
        chunks = []
        while len(text) > self._MAX_MSG_LEN:
            # Try to split at a newline near the limit
            split_at = text.rfind("\n", 0, self._MAX_MSG_LEN)
            if split_at < self._MAX_MSG_LEN // 2:
                split_at = self._MAX_MSG_LEN
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip("\n")
        if text:
            chunks.append(text)

        result: dict[str, Any] = {}
        for i, chunk in enumerate(chunks):
            payload: dict[str, Any] = {
                "chat_id": chat_id,
                "text": chunk,
            }
            # Only reply to the original message on the first chunk
            if i == 0 and reply_to_message_id:
                payload["reply_to_message_id"] = reply_to_message_id

            url = f"{self.api_endpoint}/sendMessage"
            response = await self.client.post(url, json=payload)
            response.raise_for_status()
            result = response.json()

        return result

    async def set_webhook(self, webhook_url: str) -> dict[str, Any]:
        """Register webhook URL with Telegram.

        Args:
            webhook_url: Full URL where Telegram will send updates
                        (e.g., https://api.example.com/webhooks/telegram/TOKEN).

        Returns:
            API response dict.

        Raises:
            httpx.HTTPError: If API call fails.
        """
        webhook_secret = secrets.token_urlsafe(32)
        payload = {"url": webhook_url, "secret_token": webhook_secret}
        url = f"{self.api_endpoint}/setWebhook"
        response = await self.client.post(url, json=payload)
        response.raise_for_status()
        result = response.json()
        result["webhook_secret"] = webhook_secret
        return result

    async def delete_webhook(self) -> dict[str, Any]:
        """Delete the registered webhook.

        Returns:
            API response dict.

        Raises:
            httpx.HTTPError: If API call fails.
        """
        url = f"{self.api_endpoint}/deleteWebhook"
        response = await self.client.post(url)
        response.raise_for_status()
        return response.json()

    async def get_webhook_info(self) -> dict[str, Any]:
        """Get current webhook status.

        Returns:
            API response dict with webhook_info.

        Raises:
            httpx.HTTPError: If API call fails.
        """
        url = f"{self.api_endpoint}/getWebhookInfo"
        response = await self.client.get(url)
        response.raise_for_status()
        return response.json()

    async def get_me(self) -> dict[str, Any]:
        """Get bot information.

        Returns:
            API response dict with bot user info.

        Raises:
            httpx.HTTPError: If API call fails.
        """
        url = f"{self.api_endpoint}/getMe"
        response = await self.client.get(url)
        response.raise_for_status()
        return response.json()

    def parse_update(self, data: dict[str, Any]) -> Optional[Update]:
        """Parse incoming webhook data into an Update object.

        Args:
            data: Raw JSON dict from Telegram webhook.

        Returns:
            Parsed Update object, or None if parsing fails.
        """
        try:
            update = Update(**data)
            return update
        except (TypeError, ValueError, KeyError) as e:
            logger.warning("Failed to parse Telegram update: %s", e)
            return None

    def extract_message(self, update: Update) -> Optional[dict[str, Any]]:
        """Extract message information from an update.

        Args:
            update: Parsed Update object.

        Returns:
            Dict with keys: user_id, chat_id, text, message_id, timestamp.
            Returns None if no message found.
        """
        if not update.message:
            return None

        msg = update.message
        if not msg.text:
            return None

        return {
            "user_id": msg.from_user.id,
            "chat_id": msg.chat.id,
            "text": msg.text,
            "message_id": msg.message_id,
            "timestamp": datetime.fromtimestamp(msg.date, tz=UTC),
            "username": msg.from_user.username,
        }

    def format_session_key(self, user_id: int) -> str:
        """Generate a Birkin session key from a Telegram user ID.

        The session key is used to map Telegram users to Birkin sessions.

        Args:
            user_id: Telegram user ID.

        Returns:
            Session key string (e.g., "telegram_123456789").
        """
        return f"telegram_{user_id}"

    async def get_updates(
        self,
        offset: Optional[int] = None,
        timeout: int = 30,
    ) -> list[dict[str, Any]]:
        """Long-poll for new updates (alternative to webhooks).

        Args:
            offset: ID of the first update to be returned.
            timeout: Timeout in seconds for long polling.

        Returns:
            List of Update dicts.
        """
        params: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        url = f"{self.api_endpoint}/getUpdates"
        response = await self.client.get(url, params=params, timeout=timeout + 5)
        response.raise_for_status()
        data = response.json()
        return data.get("result", [])

    @staticmethod
    def verify_secret(header_value: str, expected: str) -> bool:
        """Verify the webhook secret token using constant-time comparison.

        Args:
            header_value: Value from X-Telegram-Bot-Api-Secret-Token header.
            expected: The secret token that was registered with Telegram.

        Returns:
            True if the values match, False otherwise.
        """
        return hmac.compare_digest(header_value, expected)

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()
