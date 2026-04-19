"""Traces router — query observability trace data."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Query

from birkin.observability.storage import TraceStorage

router = APIRouter(prefix="/api/traces", tags=["traces"])

_storage: TraceStorage | None = None


def _get_storage() -> TraceStorage:
    global _storage
    if _storage is None:
        _storage = TraceStorage()
    return _storage


@router.get("")
async def list_traces(
    session_id: Optional[str] = Query(None, description="Filter by session ID"),
    limit: int = Query(20, ge=1, le=100),
) -> list[dict[str, Any]]:
    """List traces, optionally filtered by session."""
    storage = _get_storage()
    if session_id:
        traces = storage.get_latest(session_id, limit=limit)
    else:
        # Return traces from all sessions (most recent first)
        traces = []
        for sid in storage.list_sessions():
            traces.extend(storage.get_latest(sid, limit=limit))
        traces.sort(key=lambda t: t.started_at, reverse=True)
        traces = traces[:limit]

    return [t.model_dump() for t in traces]


@router.get("/sessions")
async def list_traced_sessions() -> list[str]:
    """List session IDs that have trace data."""
    return _get_storage().list_sessions()
