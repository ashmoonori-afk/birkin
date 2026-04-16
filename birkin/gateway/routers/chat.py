"""Chat endpoints (sync and SSE stream)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from starlette.responses import StreamingResponse

from birkin.core.agent import Agent
from birkin.core.providers import create_provider
from birkin.gateway.deps import get_session_store, get_wiki_memory
from birkin.gateway.schemas import ChatRequest, ChatResponse
from birkin.tools.loader import load_tools

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


def _build_agent(body: ChatRequest) -> Agent:
    """Build an Agent instance from a chat request. Shared by sync and stream endpoints."""
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

    agent_kwargs: dict = {
        "provider": provider,
        "tools": load_tools(),
        "session_store": store,
        "session_id": body.session_id,
        "memory": get_wiki_memory(),
    }
    if config.get("system_prompt") is not None:
        agent_kwargs["system_prompt"] = config["system_prompt"]
    return Agent(**agent_kwargs)


async def _drain_queue(queue: asyncio.Queue, task: asyncio.Task) -> AsyncGenerator[str, None]:
    """Drain an asyncio queue while a task is running, yielding SSE data lines."""
    while True:
        if task.done() and queue.empty():
            break
        try:
            evt = await asyncio.wait_for(queue.get(), timeout=0.05)
            yield f"data: {json.dumps(evt)}\n\n"
        except asyncio.TimeoutError:
            continue


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest) -> ChatResponse:
    """Send a message and receive the agent's reply."""
    agent = _build_agent(body)

    try:
        reply = await agent.achat(body.message)
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


@router.post("/chat/stream")
async def chat_stream(body: ChatRequest) -> StreamingResponse:
    """Send a message and stream the agent's reply via Server-Sent Events."""
    from birkin.gateway.config import load_config

    agent = _build_agent(body)
    config = load_config()

    # Check for active workflow
    active_wf_id = config.get("active_workflow")
    active_workflow = None
    if active_wf_id:
        try:
            from birkin.gateway.workflows import load_workflows

            wf_data = load_workflows()
            for wf in wf_data["saved"] + wf_data["samples"]:
                if wf.get("id") == active_wf_id:
                    active_workflow = wf
                    break
        except Exception:
            logger.warning("Failed to load active workflow %s", active_wf_id, exc_info=True)

    async def event_generator() -> AsyncGenerator[str, None]:
        queue: asyncio.Queue[dict | None] = asyncio.Queue()

        def on_delta(delta: str | None) -> None:
            if delta is not None:
                queue.put_nowait({"delta": delta})

        def on_event(evt: dict) -> None:
            queue.put_nowait(evt)

        yield f"data: {json.dumps({'session_id': agent.session_id})}\n\n"

        try:
            if active_workflow:
                async for line in _stream_workflow(
                    body, agent, active_workflow, config, queue, on_event,
                ):
                    yield line
                return

            # Normal agent flow
            task = asyncio.create_task(
                agent.astream(body.message, callback=on_delta, event_callback=on_event)
            )
            async for line in _drain_queue(queue, task):
                yield line

            reply = await task
            yield f"data: {json.dumps({'done': True, 'reply': reply})}\n\n"

        except Exception as primary_exc:
            async for line in _stream_fallback(body, agent, config, primary_exc):
                yield line

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _stream_workflow(
    body: ChatRequest,
    agent: Agent,
    workflow: dict,
    config: dict,
    queue: asyncio.Queue,
    on_event,
) -> AsyncGenerator[str, None]:
    """Stream a workflow execution via SSE."""
    from birkin.core.workflow_engine import WorkflowEngine

    provider = agent.provider
    fb_provider = None
    fb_name = config.get("fallback_provider")
    if fb_name:
        try:
            fb_provider = create_provider(f"{fb_name}/default")
        except Exception:
            logger.warning("Failed to create fallback provider %s", fb_name, exc_info=True)

    engine = WorkflowEngine(
        provider,
        fallback_provider=fb_provider,
        event_callback=on_event,
        wiki_memory=get_wiki_memory(),
    )
    engine.load(workflow)

    wf_task = asyncio.create_task(engine.run(body.message))
    async for line in _drain_queue(queue, wf_task):
        yield line

    reply = await wf_task
    from birkin.core.models import Message as Msg

    store = get_session_store()
    store.append_message(agent.session_id, Msg(role="user", content=body.message))
    store.append_message(agent.session_id, Msg(role="assistant", content=reply))
    yield f"data: {json.dumps({'done': True, 'reply': reply})}\n\n"


async def _stream_fallback(
    body: ChatRequest,
    agent: Agent,
    config: dict,
    primary_exc: Exception,
) -> AsyncGenerator[str, None]:
    """Try a fallback provider after primary failure, yielding SSE lines."""
    fallback_prov = config.get("fallback_provider")
    if fallback_prov and fallback_prov != body.provider:
        fb_msg = f"Primary failed, trying {fallback_prov}..."
        yield f"data: {json.dumps({'event': 'fallback', 'message': fb_msg})}\n\n"
        try:
            fb_provider = create_provider(f"{fallback_prov}/default")
            fb_agent = Agent(
                provider=fb_provider,
                tools=load_tools(),
                session_store=get_session_store(),
                session_id=body.session_id,
                memory=get_wiki_memory(),
            )
            fb_queue: asyncio.Queue[dict | None] = asyncio.Queue()

            def fb_on_delta(d: str | None) -> None:
                if d is not None:
                    fb_queue.put_nowait({"delta": d})

            fb_task = asyncio.create_task(fb_agent.astream(body.message, callback=fb_on_delta))
            async for line in _drain_queue(fb_queue, fb_task):
                yield line

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
