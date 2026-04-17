"""Insights engine endpoints — weekly digest, patterns, usage trend."""

from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from fastapi import APIRouter, Query

from birkin.gateway.deps import get_insights_engine

router = APIRouter(prefix="/api/insights", tags=["insights"])


@router.get("/weekly")
def insights_weekly(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict[str, Any]:
    """Return a weekly digest for the given date range.

    Defaults to the last 7 days when no dates are provided.
    """
    today = dt.date.today()
    if start_date is None:
        start_date = (today - dt.timedelta(days=6)).isoformat()
    if end_date is None:
        end_date = today.isoformat()

    engine = get_insights_engine()
    digest = engine.weekly_digest(start_date, end_date)
    return digest.model_dump()


@router.get("/patterns")
def insights_patterns(days: int = Query(default=30, ge=1, le=365)) -> list[dict[str, Any]]:
    """Return detected recurring patterns over the last *days* days."""
    engine = get_insights_engine()
    patterns = engine.identify_patterns(days=days)
    return [p.model_dump() for p in patterns]


@router.get("/trend")
def insights_trend(days: int = Query(default=7, ge=1, le=365)) -> list[dict[str, Any]]:
    """Return daily token-usage trend for the last *days* days."""
    engine = get_insights_engine()
    return engine.usage_trend(days=days)
