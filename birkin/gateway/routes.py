"""API route definitions for the Birkin gateway."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from birkin.core.agent import Agent
from birkin.core.providers import create_provider
from birkin.gateway.deps import get_session_store
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
    store = get_session_store()

    if body.session_id:
        try:
            session = store.load(body.session_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Session not found")
    else:
        session = store.create()

    provider = create_provider(body.provider, model=body.model)
    tools = load_tools()
    agent = Agent(provider=provider, tools=tools, session=session)

    try:
        reply = agent.chat(body.message)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc))

    store.save(session)
    return ChatResponse(
        session_id=session.id,
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
            message_count=s.message_count,
        )
        for s in store.list_all()
    ]


@router.post("/sessions", response_model=SessionSummary, status_code=201)
def create_session() -> SessionSummary:
    store = get_session_store()
    session = store.create()
    return SessionSummary(
        id=session.id,
        created_at=session.created_at,
        message_count=session.message_count,
    )


@router.get("/sessions/{session_id}", response_model=SessionDetail)
def get_session(session_id: str) -> SessionDetail:
    store = get_session_store()
    try:
        session = store.load(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionDetail(
        id=session.id,
        created_at=session.created_at,
        messages=[
            MessageOut(role=m.role, content=m.content) for m in session.messages
        ],
    )


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str) -> None:
    store = get_session_store()
    store.delete(session_id)
