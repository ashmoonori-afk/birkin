"""Personal insights engine — periodic analysis from compiled memory and events."""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any, Optional

from pydantic import BaseModel, Field

from birkin.memory.event_store import EventStore
from birkin.memory.events import RawEvent

logger = logging.getLogger(__name__)


class WeeklyDigest(BaseModel):
    """Auto-generated weekly summary."""

    period: str = ""  # e.g. "2026-04-14 to 2026-04-20"
    total_events: int = 0
    total_sessions: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    providers_used: list[str] = Field(default_factory=list)
    top_tools: list[str] = Field(default_factory=list)
    active_days: int = 0
    summary: str = ""


class Pattern(BaseModel):
    """A detected recurring pattern."""

    name: str
    frequency: int = 0
    description: str = ""


class InsightsEngine:
    """Generates periodic insights from event data and compiled memory.

    Analyzes raw events to produce weekly digests, detect recurring
    patterns, and track usage trends.

    Usage::

        engine = InsightsEngine(event_store)
        digest = engine.weekly_digest("2026-04-14", "2026-04-20")
        patterns = engine.identify_patterns(days=30)
    """

    def __init__(self, event_store: EventStore) -> None:
        self._store = event_store

    def weekly_digest(self, start_date: str, end_date: str) -> WeeklyDigest:
        """Generate a weekly digest for a date range.

        Args:
            start_date: ISO date string (e.g. "2026-04-14").
            end_date: ISO date string (e.g. "2026-04-20").
        """
        start_ts = f"{start_date}T00:00:00"
        end_ts = f"{end_date}T23:59:59"

        all_events = self._store.since(start_ts)
        events = [e for e in all_events if e.timestamp <= end_ts]

        if not events:
            return WeeklyDigest(period=f"{start_date} to {end_date}")

        sessions = list({e.session_id for e in events})
        total_tokens = sum((e.tokens.tokens_in + e.tokens.tokens_out) if e.tokens else 0 for e in events)
        total_cost = sum(e.tokens.cost_usd if e.tokens else 0.0 for e in events)
        providers = list({e.provider for e in events if e.provider})

        # Top tools
        tool_events = [e for e in events if e.event_type == "tool_call"]
        tool_names = [e.payload.get("name", "unknown") for e in tool_events]
        top_tools = [name for name, _ in Counter(tool_names).most_common(5)]

        # Active days
        dates = {e.timestamp[:10] for e in events}

        summary_parts = [
            f"Week of {start_date} to {end_date}:",
            f"  {len(events)} events across {len(sessions)} sessions",
            f"  {total_tokens} tokens used (${total_cost:.4f})",
            f"  Providers: {', '.join(providers) if providers else 'none'}",
        ]

        return WeeklyDigest(
            period=f"{start_date} to {end_date}",
            total_events=len(events),
            total_sessions=len(sessions),
            total_tokens=total_tokens,
            total_cost_usd=total_cost,
            providers_used=providers,
            top_tools=top_tools,
            active_days=len(dates),
            summary="\n".join(summary_parts),
        )

    def identify_patterns(self, days: int = 30) -> list[Pattern]:
        """Identify recurring patterns in recent events.

        Looks at event types, tool usage, and provider distribution
        to surface patterns the user might not be aware of.
        """
        import datetime as dt

        cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()
        events = self._store.since(cutoff)

        if not events:
            return []

        patterns: list[Pattern] = []

        # Pattern: most used provider
        providers = [e.provider for e in events if e.provider]
        if providers:
            top_provider, count = Counter(providers).most_common(1)[0]
            pct = count / len(providers) * 100
            patterns.append(Pattern(
                name=f"Primary provider: {top_provider}",
                frequency=count,
                description=f"{top_provider} used in {pct:.0f}% of LLM calls ({count}/{len(providers)})",
            ))

        # Pattern: most used tool
        tool_events = [e for e in events if e.event_type == "tool_call"]
        if tool_events:
            tool_names = [e.payload.get("name", "unknown") for e in tool_events]
            top_tool, count = Counter(tool_names).most_common(1)[0]
            patterns.append(Pattern(
                name=f"Favorite tool: {top_tool}",
                frequency=count,
                description=f"{top_tool} called {count} times in {days} days",
            ))

        # Pattern: peak usage hour
        hours = [int(e.timestamp[11:13]) for e in events if len(e.timestamp) > 13]
        if hours:
            peak_hour, count = Counter(hours).most_common(1)[0]
            patterns.append(Pattern(
                name=f"Peak activity: {peak_hour}:00",
                frequency=count,
                description=f"Most active at {peak_hour}:00 ({count} events)",
            ))

        return patterns

    def usage_trend(self, days: int = 7) -> list[dict[str, Any]]:
        """Daily token usage trend for the last N days."""
        import datetime as dt

        trend: list[dict[str, Any]] = []
        now = dt.datetime.now(dt.timezone.utc)

        for i in range(days - 1, -1, -1):
            day = (now - dt.timedelta(days=i)).strftime("%Y-%m-%d")
            start = f"{day}T00:00:00"
            end = f"{day}T23:59:59"
            day_events = [e for e in self._store.since(start) if e.timestamp <= end]
            tokens = sum((e.tokens.tokens_in + e.tokens.tokens_out) if e.tokens else 0 for e in day_events)
            cost = sum(e.tokens.cost_usd if e.tokens else 0.0 for e in day_events)
            trend.append({"date": day, "tokens": tokens, "cost_usd": cost, "events": len(day_events)})

        return trend
