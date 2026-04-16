"""Telegram management and polling endpoints."""

from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from birkin.gateway.deps import get_dispatcher, get_telegram_adapter

router = APIRouter(prefix="/api", tags=["telegram"])

# Polling state
_polling_task: Optional[asyncio.Task] = None  # type: ignore[type-arg]
_polling_active = False

# Health monitoring state
_health_status: dict[str, Any] = {"ok": True, "last_check": None, "error": None}

# Concurrency lock for start/stop polling
_polling_lock = asyncio.Lock()


@router.get("/telegram/status")
async def telegram_status() -> dict:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        return {"configured": False, "bot_info": None, "webhook_info": None}
    try:
        adapter = get_telegram_adapter()
        bot_info = await adapter.get_me()
        webhook_info = await adapter.get_webhook_info()
        return {
            "configured": True,
            "bot_info": bot_info.get("result"),
            "webhook_info": webhook_info.get("result"),
            "polling": _polling_active,
        }
    except (ConnectionError, TimeoutError, OSError) as e:
        return {
            "configured": False,
            "bot_info": None,
            "webhook_info": None,
            "polling": False,
            "error": str(e),
        }


@router.get("/telegram/health")
async def telegram_health() -> dict:
    """Get Telegram connection health status."""
    return {
        **_health_status,
        "polling_active": _polling_active,
    }


async def _health_check_loop() -> None:
    """Background loop checking Telegram health every 60 seconds."""
    global _polling_task  # noqa: PLW0603

    import logging
    from datetime import datetime, timezone

    log = logging.getLogger("birkin.telegram.health")

    while True:
        await asyncio.sleep(60)
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            _health_status.update(
                ok=False,
                error="No token",
                last_check=datetime.now(timezone.utc).isoformat(),
            )
            continue

        try:
            adapter = get_telegram_adapter()

            # Check if polling task crashed
            if _polling_active and _polling_task and _polling_task.done():
                exc = _polling_task.exception() if not _polling_task.cancelled() else None
                _health_status.update(
                    ok=False,
                    error=(f"Polling crashed: {exc}" if exc else "Polling stopped unexpectedly"),
                    last_check=datetime.now(timezone.utc).isoformat(),
                )
                log.error("Polling task died, restarting...")
                # Auto-restart polling
                _polling_task = asyncio.create_task(_poll_loop(adapter))
                continue

            # Check webhook health if webhook is set
            wh_info = await adapter.get_webhook_info()
            result = wh_info.get("result", {})
            if result.get("last_error_message"):
                _health_status.update(
                    ok=False,
                    error=result["last_error_message"],
                    last_check=datetime.now(timezone.utc).isoformat(),
                )
            else:
                _health_status.update(
                    ok=True,
                    error=None,
                    last_check=datetime.now(timezone.utc).isoformat(),
                )

        except (ConnectionError, TimeoutError, OSError) as e:
            _health_status.update(
                ok=False,
                error=str(e),
                last_check=datetime.now(timezone.utc).isoformat(),
            )
            log.warning("Health check failed: %s", e, exc_info=True)


@router.post("/telegram/webhook")
async def telegram_set_webhook(body: dict) -> dict:
    from birkin.gateway.config import load_config, save_config

    webhook_url = body.get("webhook_url", "")
    if not webhook_url:
        raise HTTPException(status_code=400, detail="webhook_url required")
    try:
        adapter = get_telegram_adapter()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    result = await adapter.set_webhook(webhook_url)

    # Persist the generated webhook secret so incoming requests can be verified
    webhook_secret = result.pop("webhook_secret", None)
    if webhook_secret:
        config = load_config()
        config["telegram_webhook_secret"] = webhook_secret
        save_config(config)

    return result


@router.delete("/telegram/webhook")
async def telegram_delete_webhook() -> dict:
    try:
        adapter = get_telegram_adapter()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    result = await adapter.delete_webhook()
    return result


@router.post("/telegram/polling/start")
async def telegram_start_polling() -> dict:
    """Start long-polling for Telegram updates (no public URL needed)."""
    global _polling_task, _polling_active  # noqa: PLW0603

    async with _polling_lock:
        if _polling_active:
            return {"status": "already_running"}

        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            raise HTTPException(status_code=400, detail="TELEGRAM_BOT_TOKEN not set")

        try:
            adapter = get_telegram_adapter()
            # Delete any existing webhook so polling works
            await adapter.delete_webhook()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        _polling_active = True
        _polling_task = asyncio.create_task(_poll_loop(adapter))
        return {"status": "started"}


@router.post("/telegram/send-test")
async def telegram_send_test(body: dict) -> dict:
    """Send a test message to a specific chat_id."""
    chat_id = body.get("chat_id")
    if not chat_id:
        raise HTTPException(status_code=400, detail="chat_id required")
    try:
        chat_id = int(chat_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="chat_id must be a number")
    try:
        adapter = get_telegram_adapter()
        result = await adapter.send_message(
            chat_id=chat_id,
            text="Birkin is connected! \u2705\nYou can now send messages to this bot.",
        )
        return {"status": "ok", "result": result.get("result", {})}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except (ConnectionError, TimeoutError, OSError) as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/telegram/polling/stop")
async def telegram_stop_polling() -> dict:
    """Stop the polling loop."""
    global _polling_active  # noqa: PLW0603

    async with _polling_lock:
        _polling_active = False
        if _polling_task and not _polling_task.done():
            _polling_task.cancel()
        return {"status": "stopped"}


async def _poll_loop(adapter: Any) -> None:
    """Background loop that long-polls Telegram for updates."""
    global _polling_active  # noqa: PLW0603

    import logging

    log = logging.getLogger("birkin.telegram.polling")
    offset = None
    dispatcher = get_dispatcher()

    log.info("Telegram polling started")

    while _polling_active:
        try:
            updates = await adapter.get_updates(offset=offset, timeout=25)
            for raw_update in updates:
                offset = raw_update.get("update_id", 0) + 1
                update = adapter.parse_update(raw_update)
                if not update:
                    continue
                msg_info = adapter.extract_message(update)
                if not msg_info:
                    continue

                session_key = adapter.format_session_key(msg_info["user_id"])
                try:
                    reply = await dispatcher.dispatch_message(
                        text=msg_info["text"],
                        session_key=session_key,
                    )
                    await adapter.send_message(
                        chat_id=msg_info["chat_id"],
                        text=reply,
                        reply_to_message_id=msg_info["message_id"],
                    )
                except (ConnectionError, TimeoutError, RuntimeError, TypeError, ValueError, OSError) as e:
                    log.error("Failed to process message: %s", e, exc_info=True)
                    try:
                        await adapter.send_message(
                            chat_id=msg_info["chat_id"],
                            text=f"Error: {str(e)[:200]}",
                        )
                    except (ConnectionError, TimeoutError, OSError):
                        log.warning("Failed to send error reply to user", exc_info=True)
        except asyncio.CancelledError:
            break
        except (ConnectionError, TimeoutError, OSError) as e:
            log.error("Polling error: %s", e, exc_info=True)
            await asyncio.sleep(3)

    _polling_active = False
    log.info("Telegram polling stopped")
