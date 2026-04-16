"""Incoming webhook endpoints for platform adapters."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException, Request

from birkin.gateway.deps import get_dispatcher, get_telegram_adapter

router = APIRouter(prefix="/api", tags=["webhooks"])


@router.post("/webhooks/telegram/{bot_token}")
async def telegram_webhook(bot_token: str, request: Request, data: dict) -> dict[str, str]:
    """Receive messages from Telegram Bot API webhook.

    Args:
        bot_token: Bot token (should match configured TELEGRAM_BOT_TOKEN).
        request: The incoming HTTP request (used to read secret header).
        data: Telegram Update object (JSON).

    Returns:
        JSON response indicating success.

    Raises:
        HTTPException: If token doesn't match or message processing fails.
    """
    from birkin.gateway.config import load_config
    from birkin.gateway.platforms.telegram_adapter import TelegramAdapter

    # Verify webhook secret token if configured (defence layer 1)
    config = load_config()
    expected_secret = config.get("telegram_webhook_secret")
    if expected_secret:
        header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not header_secret or not TelegramAdapter.verify_secret(header_secret, expected_secret):
            raise HTTPException(status_code=403, detail="Invalid webhook secret")

    # Verify token matches configured bot (defence layer 2)
    configured_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if bot_token != configured_token:
        raise HTTPException(status_code=401, detail="Invalid bot token")

    adapter = get_telegram_adapter()
    dispatcher = get_dispatcher()

    # Parse update
    update = adapter.parse_update(data)
    if not update:
        return {"status": "invalid_update"}

    # Extract message info
    msg_info = adapter.extract_message(update)
    if not msg_info:
        return {"status": "no_message"}

    try:
        # Generate session key from Telegram user ID
        session_key = adapter.format_session_key(msg_info["user_id"])

        # Dispatch message to agent (provider from config)
        reply = await dispatcher.dispatch_message(
            text=msg_info["text"],
            session_key=session_key,
        )

        # Send reply back to Telegram
        await adapter.send_message(
            chat_id=msg_info["chat_id"],
            text=reply,
            reply_to_message_id=msg_info["message_id"],
        )

        return {"status": "ok", "reply": reply}

    except (ConnectionError, TimeoutError, RuntimeError, TypeError, ValueError, OSError) as e:
        error_msg = f"Error processing message: {str(e)}"
        try:
            await adapter.send_message(
                chat_id=msg_info["chat_id"],
                text="Sorry, I encountered an error processing your message.",
            )
        except (ConnectionError, TimeoutError, OSError):
            logging.getLogger(__name__).warning("Failed to send error reply via webhook", exc_info=True)
        raise HTTPException(status_code=500, detail=error_msg)
