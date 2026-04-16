"""Session CRUD endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from birkin.gateway.deps import get_session_store
from birkin.gateway.schemas import MessageOut, SessionDetail, SessionSummary

router = APIRouter(prefix="/api", tags=["sessions"])


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
