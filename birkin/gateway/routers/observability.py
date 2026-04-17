"""Observability dashboard router — spend, latency, error endpoints."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Optional

from fastapi import APIRouter, Query

from birkin.gateway.deps import get_wiki_memory
from birkin.gateway.observability.aggregator import MetricsAggregator
from birkin.observability.storage import TraceStorage

logger = logging.getLogger(__name__)

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


@router.get("/hero")
async def hero_metrics() -> dict[str, int]:
    """Dashboard hero metrics — 'prove it' numbers for the landing panel."""
    now = dt.datetime.now(dt.timezone.utc)
    week_ago = now - dt.timedelta(days=7)

    # --- tokens saved (compression spans in last 7 days) ---
    tokens_saved = 0
    try:
        agg = _get_aggregator()
        storage = agg._storage  # noqa: SLF001
        for sid in storage.list_sessions():
            for trace in storage.query(sid):
                if not trace.started_at:
                    continue
                for span in trace.spans:
                    attrs = span.attributes or {}
                    # Count tokens_saved from compression spans
                    if attrs.get("compression") or "compress" in span.name.lower():
                        tokens_saved += attrs.get("tokens_saved", 0)
                    # Estimate savings from context injection (tokens_in reduction)
                    if "context" in span.name.lower() or "memory" in span.name.lower():
                        tokens_saved += attrs.get("tokens_reduced", 0)
    except (OSError, AttributeError, RuntimeError) as exc:
        logger.warning("hero: could not compute tokens_saved: %s", exc)

    # --- automations run (workflow/trigger traces in last 7 days) ---
    automations_run = 0
    try:
        storage = _get_aggregator()._storage  # noqa: SLF001
        for sid in storage.list_sessions():
            for trace in storage.query(sid):
                # Count traces that have workflow_id OR contain workflow/trigger spans
                if getattr(trace, "workflow_id", None):
                    automations_run += 1
                    continue
                for span in trace.spans:
                    if "workflow" in span.name.lower() or "trigger" in span.name.lower():
                        automations_run += 1
                        break
    except (OSError, AttributeError, RuntimeError) as exc:
        logger.warning("hero: could not compute automations_run: %s", exc)

    # --- memory pages ---
    memory_total = 0
    memory_delta = 0
    try:
        wiki = get_wiki_memory()
        memory_total = wiki.page_count()
        memory_delta = wiki.pages_created_since(week_ago)
    except (OSError, AttributeError, RuntimeError) as exc:
        logger.warning("hero: could not compute memory metrics: %s", exc)

    return {
        "tokens_saved_this_week": tokens_saved,
        "automations_run": automations_run,
        "memory_pages_total": memory_total,
        "memory_pages_delta_week": memory_delta,
    }
