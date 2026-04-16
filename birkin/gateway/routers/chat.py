"""Chat endpoints (sync and SSE stream)."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from starlette.responses import StreamingResponse

from birkin.core.agent import Agent
from birkin.core.providers import create_provider
from birkin.gateway.deps import get_session_store, get_wiki_memory
from birkin.gateway.schemas import ChatRequest, ChatResponse
from birkin.tools.loader import load_tools

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest) -> ChatResponse:
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
            pass

    async def event_generator() -> AsyncGenerator[str, None]:
        queue: asyncio.Queue[dict | None] = asyncio.Queue()

        def on_delta(delta: str | None) -> None:
            if delta is not None:
                queue.put_nowait({"delta": delta})

        def on_event(evt: dict) -> None:
            queue.put_nowait(evt)

        yield f"data: {json.dumps({'session_id': agent.session_id})}\n\n"

        try:
            # If a workflow is active, use the workflow engine
            if active_workflow:
                from birkin.core.workflow_engine import WorkflowEngine

                fb_provider = None
                fb_name = config.get("fallback_provider")
                if fb_name:
                    try:
                        fb_provider = create_provider(f"{fb_name}/default")
                    except Exception:
                        pass

                engine = WorkflowEngine(
                    provider,
                    fallback_provider=fb_provider,
                    event_callback=on_event,
                    wiki_memory=get_wiki_memory(),
                )
                engine.load(active_workflow)

                wf_task: asyncio.Task[str] = asyncio.create_task(engine.run(body.message))

                while True:
                    if wf_task.done() and queue.empty():
                        break
                    try:
                        evt = await asyncio.wait_for(queue.get(), timeout=0.05)
                        yield f"data: {json.dumps(evt)}\n\n"
                    except asyncio.TimeoutError:
                        continue

                reply = await wf_task
                # Store messages in session
                from birkin.core.models import Message as Msg

                store.append_message(agent.session_id, Msg(role="user", content=body.message))
                store.append_message(agent.session_id, Msg(role="assistant", content=reply))
                yield f"data: {json.dumps({'done': True, 'reply': reply})}\n\n"
                return

            # Normal agent flow
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
