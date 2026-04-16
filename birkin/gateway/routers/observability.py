"""Observability dashboard router — spend, latency, error endpoints."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Query

from birkin.gateway.observability.aggregator import MetricsAggregator
from birkin.observability.storage import TraceStorage

router = APIRouter(prefix="/api/observability", tags=["observability"])

_aggregator: MetricsAggregator | None = None


def _get_aggregator() -> MetricsAggregator:
    global _aggregator  # noqa: PLW0603
    if _aggregator is None:
        _aggregator = MetricsAggregator(TraceStorage())
    return _aggregator


@router.get("/spend")
async def token_spend(session_id: Optional[str] = Query(None)) -> dict[str, Any]:
    """Token spend summary, optionally filtered by session."""
    agg = _get_aggregator()
    sids = [session_id] if session_id else None
    return agg.token_spend(sids).model_dump()


@router.get("/latency")
async def latency_stats(session_id: Optional[str] = Query(None)) -> dict[str, Any]:
    """Latency statistics across spans."""
    agg = _get_aggregator()
    sids = [session_id] if session_id else None
    return agg.latency_stats(sids).model_dump()


@router.get("/errors")
async def error_summary(session_id: Optional[str] = Query(None)) -> dict[str, Any]:
    """Error rate and top errors."""
    agg = _get_aggregator()
    sids = [session_id] if session_id else None
    return agg.error_summary(sids).model_dump()
