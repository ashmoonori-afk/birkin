"""API route definitions for the Birkin gateway."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, AsyncGenerator, Optional

from fastapi import APIRouter, HTTPException
from starlette.responses import StreamingResponse

from birkin.core.agent import Agent
from birkin.core.providers import create_provider
from birkin.gateway.deps import (
    get_dispatcher,
    get_session_store,
    get_telegram_adapter,
    get_wiki_memory,
)
from birkin.gateway.schemas import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    MessageOut,
    SessionDetail,
    SessionSummary,
)
from birkin.tools.loader import load_tools

router = APIRouter(prefix="/api")


# --- Health ----------------------------------------------------------------


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


# --- Chat ------------------------------------------------------------------


@router.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest) -> ChatResponse:
    """Send a message and receive the agent's reply."""
    from birkin.gateway.config import load_config

    store = get_session_store()
    config = load_config()

    # Validate existing session if provided
    if body.session_id:
        try:
            store.load(body.session_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Session not found")

    # Build model string: "provider/model" or "provider/default"
    model_str = f"{body.provider}/{body.model}" if body.model else f"{body.provider}/default"
    try:
        provider = create_provider(model_str)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    tools = load_tools()

    agent_kwargs: dict = {
        "provider": provider,
        "tools": tools,
        "session_store": store,
        "session_id": body.session_id,
        "memory": get_wiki_memory(),
    }
    if config.get("system_prompt") is not None:
        agent_kwargs["system_prompt"] = config["system_prompt"]
    agent = Agent(**agent_kwargs)

    try:
        reply = agent.chat(body.message)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc))
    except TypeError as exc:
        # Catches missing API key errors from provider SDKs
        msg = str(exc)
        if "api_key" in msg or "auth" in msg.lower():
            raise HTTPException(
                status_code=401,
                detail=(
                    f"API key not configured for provider '{body.provider}'. "
                    "Set the appropriate environment variable "
                    "(ANTHROPIC_API_KEY or OPENAI_API_KEY) in your .env file."
                ),
            )
        raise HTTPException(status_code=500, detail=msg)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return ChatResponse(
        session_id=agent.session_id,
        reply=reply,
    )


# --- Chat SSE Stream -------------------------------------------------------


@router.post("/chat/stream")
async def chat_stream(body: ChatRequest) -> StreamingResponse:
    """Send a message and stream the agent's reply via Server-Sent Events."""
    from birkin.gateway.config import load_config

    store = get_session_store()
    config = load_config()

    if body.session_id:
        try:
            store.load(body.session_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Session not found")

    model_str = f"{body.provider}/{body.model}" if body.model else f"{body.provider}/default"
    try:
        provider = create_provider(model_str)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    tools = load_tools()

    agent_kwargs: dict = {
        "provider": provider,
        "tools": tools,
        "session_store": store,
        "session_id": body.session_id,
        "memory": get_wiki_memory(),
    }
    if config.get("system_prompt") is not None:
        agent_kwargs["system_prompt"] = config["system_prompt"]
    agent = Agent(**agent_kwargs)

    async def event_generator() -> AsyncGenerator[str, None]:
        # Unified queue — all events go here in order
        queue: asyncio.Queue[dict | None] = asyncio.Queue()

        def on_delta(delta: str | None) -> None:
            if delta is not None:
                queue.put_nowait({"delta": delta})
            # delta=None means stream end — we handle via task completion

        def on_event(evt: dict) -> None:
            queue.put_nowait(evt)

        # Send session_id first
        yield f"data: {json.dumps({'session_id': agent.session_id})}\n\n"

        try:
            task: asyncio.Task[str] = asyncio.create_task(
                agent.astream(body.message, callback=on_delta, event_callback=on_event)
            )

            # Drain queue in real-time using get() with timeout
            while True:
                if task.done() and queue.empty():
                    break
                try:
                    evt = await asyncio.wait_for(queue.get(), timeout=0.05)
                    yield f"data: {json.dumps(evt)}\n\n"
                except asyncio.TimeoutError:
                    continue

            reply = await task
            yield f"data: {json.dumps({'done': True, 'reply': reply})}\n\n"

        except Exception as primary_exc:
            # Try fallback provider if configured
            fallback_prov = config.get("fallback_provider")
            if fallback_prov and fallback_prov != body.provider:
                fb_msg = f"Primary failed, trying {fallback_prov}..."
                yield f"data: {json.dumps({'event': 'fallback', 'message': fb_msg})}\n\n"
                try:
                    fb_model = f"{fallback_prov}/default"
                    fb_provider = create_provider(fb_model)
                    fb_kwargs = dict(agent_kwargs)
                    fb_kwargs["provider"] = fb_provider
                    fb_agent = Agent(**fb_kwargs)
                    fb_queue: asyncio.Queue[dict | None] = asyncio.Queue()

                    def fb_on_delta(d: str | None) -> None:
                        if d is not None:
                            fb_queue.put_nowait({"delta": d})

                    fb_task = asyncio.create_task(fb_agent.astream(body.message, callback=fb_on_delta))

                    while True:
                        if fb_task.done() and fb_queue.empty():
                            break
                        try:
                            evt = await asyncio.wait_for(fb_queue.get(), timeout=0.05)
                            yield f"data: {json.dumps(evt)}\n\n"
                        except asyncio.TimeoutError:
                            continue

                    reply = await fb_task
                    yield f"data: {json.dumps({'done': True, 'reply': reply})}\n\n"
                    return
                except Exception as fb_exc:
                    err = f"Both providers failed. Primary: {primary_exc}, Fallback: {fb_exc}"
                    yield f"data: {json.dumps({'error': err})}\n\n"
                    return

            # No fallback — report primary error
            msg = str(primary_exc)
            if "api_key" in msg or "auth" in msg.lower():
                yield f"data: {json.dumps({'error': f'API key not configured for {body.provider}'})}\n\n"
            else:
                yield f"data: {json.dumps({'error': msg})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# --- Settings ---------------------------------------------------------------


@router.get("/settings")
def get_settings() -> dict:
    """Get current configuration."""
    from birkin.gateway.config import load_config

    return load_config()


@router.put("/settings")
def update_settings(body: dict) -> dict:
    """Update configuration."""
    from birkin.gateway.config import load_config, save_config

    config = load_config()
    config.update(body)
    save_config(config)
    return config


_ALLOWED_KEY_NAMES = frozenset({"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "TELEGRAM_BOT_TOKEN"})


@router.put("/settings/keys")
def update_api_keys(body: dict) -> dict:
    """Write API keys to the .env file and update os.environ.

    Accepts ``{"ANTHROPIC_API_KEY": "sk-...", "OPENAI_API_KEY": "sk-..."}``.
    Only key names in the allow-list are accepted.
    """
    from pathlib import Path

    invalid = set(body.keys()) - _ALLOWED_KEY_NAMES
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid key names: {sorted(invalid)}. Allowed: {sorted(_ALLOWED_KEY_NAMES)}",
        )

    # Read existing .env (preserving unrelated lines)
    env_path = Path(".env")
    existing_lines: list[str] = []
    if env_path.exists():
        existing_lines = env_path.read_text(encoding="utf-8").splitlines()

    # Parse existing key=value pairs and rebuild
    updated_keys: set[str] = set()
    new_lines: list[str] = []
    for line in existing_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            key_part = stripped.split("=", 1)[0]
            if key_part in body:
                new_lines.append(f"{key_part}={body[key_part]}")
                updated_keys.add(key_part)
                continue
        new_lines.append(line)

    # Append keys not yet present
    for key_name, key_value in body.items():
        if key_name not in updated_keys:
            new_lines.append(f"{key_name}={key_value}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    # Set in current process immediately
    saved: list[str] = []
    for key_name, key_value in body.items():
        os.environ[key_name] = key_value
        saved.append(key_name)

    # Reset Telegram adapter if token changed (so it picks up the new one)
    if "TELEGRAM_BOT_TOKEN" in body:
        from birkin.gateway.deps import reset_telegram_adapter

        reset_telegram_adapter()

    return {"saved": sorted(saved)}


@router.get("/settings/providers")
def detect_providers() -> dict:
    """Detect available providers (API keys, local CLIs)."""
    import shutil

    results = {
        "anthropic": {
            "available": bool(os.getenv("ANTHROPIC_API_KEY")),
            "type": "api",
            "needs_key": True,
            "key_env": "ANTHROPIC_API_KEY",
            "models": ["claude-opus-4-20250805", "claude-sonnet-4-20250514"],
        },
        "openai": {
            "available": bool(os.getenv("OPENAI_API_KEY")),
            "type": "api",
            "needs_key": True,
            "key_env": "OPENAI_API_KEY",
            "models": ["gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"],
        },
        "claude-cli": {
            "available": shutil.which("claude") is not None,
            "type": "local",
            "needs_key": False,
            "description": "Claude Code CLI (local)",
        },
        "codex-cli": {
            "available": shutil.which("codex") is not None,
            "type": "local",
            "needs_key": False,
            "description": "OpenAI Codex CLI (local)",
        },
    }
    return results


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
        messages=[MessageOut(role=m.role, content=m.content) for m in messages],
    )


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str) -> None:
    store = get_session_store()
    store.delete_session(session_id)


# --- Workflows ---------------------------------------------------------------


@router.get("/workflows")
def list_workflows():
    """List all workflows (saved + samples)."""
    from birkin.gateway.workflows import load_workflows

    return load_workflows()


@router.get("/workflows/{workflow_id}")
def get_workflow(workflow_id: str):
    """Get a single workflow by ID."""
    from birkin.gateway.workflows import load_workflows

    data = load_workflows()
    for w in data["saved"] + data["samples"]:
        if w.get("id") == workflow_id:
            return w
    raise HTTPException(status_code=404, detail="Workflow not found")


@router.put("/workflows")
def put_workflow(body: dict):
    """Save or update a workflow."""
    import uuid

    from birkin.gateway.workflows import save_workflow

    if "id" not in body:
        body["id"] = uuid.uuid4().hex[:12]
    save_workflow(body)
    return {"status": "ok", "id": body["id"]}


@router.delete("/workflows/{workflow_id}", status_code=204)
def remove_workflow(workflow_id: str):
    """Delete a saved workflow."""
    from birkin.gateway.workflows import delete_workflow

    delete_workflow(workflow_id)


# --- Wiki Memory ---------------------------------------------------------------


@router.get("/wiki/pages")
def wiki_list_pages():
    wiki = get_wiki_memory()
    return wiki.list_pages()


@router.get("/wiki/pages/{category}/{slug}")
def wiki_get_page(category: str, slug: str):
    wiki = get_wiki_memory()
    content = wiki.get_page(category, slug)
    if content is None:
        raise HTTPException(status_code=404, detail="Page not found")
    return {"category": category, "slug": slug, "content": content}


@router.put("/wiki/pages/{category}/{slug}")
def wiki_put_page(category: str, slug: str, body: dict):
    wiki = get_wiki_memory()
    wiki.ingest(category, slug, body.get("content", ""))
    return {"status": "ok"}


@router.delete("/wiki/pages/{category}/{slug}", status_code=204)
def wiki_delete_page(category: str, slug: str):
    wiki = get_wiki_memory()
    wiki.delete_page(category, slug)


@router.get("/wiki/search")
def wiki_search(q: str = ""):
    wiki = get_wiki_memory()
    return wiki.query(q) if q else []


@router.get("/wiki/lint")
def wiki_lint():
    wiki = get_wiki_memory()
    return {"warnings": wiki.lint()}


@router.get("/wiki/graph")
def wiki_graph():
    """Build node-link graph data from wiki pages."""
    import re

    wiki = get_wiki_memory()
    pages = wiki.list_pages()
    wikilink_re = re.compile(r"\[\[([^\]]+)\]\]")

    nodes = []
    edges = []
    all_slugs = set()
    referenced = set()

    for p in pages:
        slug = p["slug"]
        cat = p["category"]
        all_slugs.add(slug)
        nodes.append({"slug": slug, "category": cat})

        content = wiki.get_page(cat, slug) or ""
        for m in wikilink_re.finditer(content):
            target = m.group(1).strip()
            referenced.add(target)
            edges.append({"source": slug, "target": target})

    orphans = list(all_slugs - referenced)
    # Add nodes for broken link targets
    for ref in referenced - all_slugs:
        nodes.append({"slug": ref, "category": "broken"})

    return {"nodes": nodes, "edges": edges, "orphans": orphans}


# --- Telegram Management ------------------------------------------------------

# Polling state
_polling_task: Optional[asyncio.Task] = None  # type: ignore[type-arg]
_polling_active = False


@router.get("/telegram/status")
async def telegram_status():
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
    except Exception as e:
        return {
            "configured": False,
            "bot_info": None,
            "webhook_info": None,
            "polling": False,
            "error": str(e),
        }


@router.post("/telegram/webhook")
async def telegram_set_webhook(body: dict):
    webhook_url = body.get("webhook_url", "")
    if not webhook_url:
        raise HTTPException(status_code=400, detail="webhook_url required")
    try:
        adapter = get_telegram_adapter()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    result = await adapter.set_webhook(webhook_url)
    return result


@router.delete("/telegram/webhook")
async def telegram_delete_webhook():
    try:
        adapter = get_telegram_adapter()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    result = await adapter.delete_webhook()
    return result


# --- Telegram Polling ----------------------------------------------------------


@router.post("/telegram/polling/start")
async def telegram_start_polling():
    """Start long-polling for Telegram updates (no public URL needed)."""
    global _polling_task, _polling_active  # noqa: PLW0603

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
async def telegram_send_test(body: dict):
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
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/telegram/polling/stop")
async def telegram_stop_polling():
    """Stop the polling loop."""
    global _polling_active  # noqa: PLW0603

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
                except Exception as e:
                    log.error(f"Failed to process message: {e}")
                    try:
                        await adapter.send_message(
                            chat_id=msg_info["chat_id"],
                            text=f"Error: {str(e)[:200]}",
                        )
                    except Exception:
                        pass
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error(f"Polling error: {e}")
            await asyncio.sleep(3)

    _polling_active = False
    log.info("Telegram polling stopped")


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

    except Exception as e:
        error_msg = f"Error processing message: {str(e)}"
        try:
            await adapter.send_message(
                chat_id=msg_info["chat_id"],
                text="Sorry, I encountered an error processing your message.",
            )
        except Exception:
            # If we can't even send error, just log it
            pass
        raise HTTPException(status_code=500, detail=error_msg)
