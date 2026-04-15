"""API route definitions for the Birkin gateway."""

from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, HTTPException

from birkin.core.agent import Agent
from birkin.core.providers import create_provider
from birkin.gateway.deps import get_session_store
from birkin.gateway.dispatcher import MessageDispatcher
from birkin.gateway.schemas import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    MessageOut,
    SessionDetail,
    SessionSummary,
)
from birkin.gateway.platforms.telegram_adapter import TelegramAdapter
from birkin.tools.loader import load_tools

router = APIRouter(prefix="/api")

# Platform adapters (lazy-initialized)
_telegram_adapter: Optional[TelegramAdapter] = None
_dispatcher: Optional[MessageDispatcher] = None


def get_telegram_adapter() -> TelegramAdapter:
    """Get or create Telegram adapter."""
    global _telegram_adapter  # noqa: PLW0603
    if _telegram_adapter is None:
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN not set")
        _telegram_adapter = TelegramAdapter(token)
    return _telegram_adapter


def get_dispatcher() -> MessageDispatcher:
    """Get or create message dispatcher."""
    global _dispatcher  # noqa: PLW0603
    if _dispatcher is None:
        _dispatcher = MessageDispatcher()
    return _dispatcher


# --- Health ----------------------------------------------------------------


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


# --- Chat ------------------------------------------------------------------


@router.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest) -> ChatResponse:
    """Send a message and receive the agent's reply."""
    store = get_session_store()

    # Validate existing session if provided
    if body.session_id:
        try:
            store.load(body.session_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Session not found")

    # Build model string: "provider/model" or "provider/default"
    model_str = (
        f"{body.provider}/{body.model}" if body.model else f"{body.provider}/default"
    )
    provider = create_provider(model_str)
    tools = load_tools()
    agent = Agent(
        provider=provider,
        tools=tools,
        session_store=store,
        session_id=body.session_id,
    )

    try:
        reply = agent.chat(body.message)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc))

    return ChatResponse(
        session_id=agent.session_id,
        reply=reply,
    )


# --- Sessions --------------------------------------------------------------


@router.get("/sessions", response_model=list[SessionSummary])
def list_sessions() -> list[SessionSummary]:
    store = get_session_store()
    return [
        SessionSummary(
            id=s.id,
            created_at=s.created_at,
            message_count=store.get_message_count(s.id),
        )
        for s in store.list_sessions()
    ]


@router.post("/sessions", response_model=SessionSummary, status_code=201)
def create_session() -> SessionSummary:
    store = get_session_store()
    session = store.create()
    return SessionSummary(
        id=session.id,
        created_at=session.created_at,
        message_count=store.get_message_count(session.id),
    )


@router.get("/sessions/{session_id}", response_model=SessionDetail)
def get_session(session_id: str) -> SessionDetail:
    store = get_session_store()
    try:
        session = store.load(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = store.get_messages(session_id)
    return SessionDetail(
        id=session.id,
        created_at=session.created_at,
        messages=[
            MessageOut(role=m.role, content=m.content) for m in messages
        ],
    )


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str) -> None:
    store = get_session_store()
    store.delete_session(session_id)


# --- Webhooks (Platform Adapters) -----------------------------------------------


@router.post("/webhooks/telegram/{bot_token}")
async def telegram_webhook(bot_token: str, data: dict) -> dict[str, str]:
    """Receive messages from Telegram Bot API webhook.

    Args:
        bot_token: Bot token (should match configured TELEGRAM_BOT_TOKEN).
        data: Telegram Update object (JSON).

    Returns:
        JSON response indicating success.

    Raises:
        HTTPException: If token doesn't match or message processing fails.
    """
    # Verify token matches configured bot
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

        # Dispatch message to agent
        reply = await dispatcher.dispatch_message(
            text=msg_info["text"],
            session_key=session_key,
            provider="anthropic",
        )

        # Send reply back to Telegram
        await adapter.send_message(
            chat_id=msg_info["chat_id"],
            text=reply,
            reply_to_message_id=msg_info["message_id"],
        )

        return {"status": "ok", "reply": reply}

    except Exception as e:
        error_msg = f"Error processing message: {str(e)}"
        try:
            await adapter.send_message(
                chat_id=msg_info["chat_id"],
                text="Sorry, I encountered an error processing your message.",
            )
        except Exception as send_error:
            # If we can't even send error, just log it
            pass
        raise HTTPException(status_code=500, detail=error_msg)
