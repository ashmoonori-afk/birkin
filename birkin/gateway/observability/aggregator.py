"""Metrics aggregator — compute dashboard stats from trace data."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from birkin.observability.storage import TraceStorage
from birkin.observability.trace import Trace


class SpendReport(BaseModel):
    """Token spend summary."""

    total_tokens: int = 0
    total_cost_usd: float = 0.0
    by_provider: dict[str, int] = {}
    session_count: int = 0


class LatencyStats(BaseModel):
    """Latency statistics."""

    avg_ms: float = 0.0
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    max_ms: float = 0.0
    span_count: int = 0


class ErrorSummary(BaseModel):
    """Error rate summary."""

    total_traces: int = 0
    error_traces: int = 0
    error_rate: float = 0.0
    top_errors: list[str] = []


class MetricsAggregator:
    """Aggregates trace data into dashboard metrics.

    Usage::

        agg = MetricsAggregator(trace_storage)
        spend = agg.token_spend()
        latency = agg.latency_stats()
        errors = agg.error_summary()
    """

    def __init__(self, storage: TraceStorage) -> None:
        self._storage = storage

    def _load_all_traces(self, session_ids: Optional[list[str]] = None) -> list[Trace]:
        sids = session_ids or self._storage.list_sessions()
        traces: list[Trace] = []
        for sid in sids:
            traces.extend(self._storage.query(sid))
        return traces

    def token_spend(self, session_ids: Optional[list[str]] = None) -> SpendReport:
        """Compute token spend across sessions."""
        traces = self._load_all_traces(session_ids)
        total_tokens = 0
        by_provider: dict[str, int] = {}

        for trace in traces:
            for span in trace.spans:
                tokens = (span.tokens_in or 0) + (span.tokens_out or 0)
                total_tokens += tokens
                if span.provider:
                    by_provider[span.provider] = by_provider.get(span.provider, 0) + tokens

        return SpendReport(
            total_tokens=total_tokens,
            by_provider=by_provider,
            session_count=len(set(t.session_id for t in traces if t.session_id)),
        )

    def latency_stats(self, session_ids: Optional[list[str]] = None) -> LatencyStats:
        """Compute latency statistics from spans."""
        traces = self._load_all_traces(session_ids)
        latencies: list[float] = []

        for trace in traces:
            for span in trace.spans:
                if span.latency_ms > 0:
                    latencies.append(float(span.latency_ms))

        if not latencies:
            return LatencyStats()

        latencies.sort()
        n = len(latencies)
        return LatencyStats(
            avg_ms=sum(latencies) / n,
            p50_ms=latencies[n // 2],
            p95_ms=latencies[int(n * 0.95)],
            max_ms=latencies[-1],
            span_count=n,
        )

    def error_summary(self, session_ids: Optional[list[str]] = None) -> ErrorSummary:
        """Compute error rates and common errors."""
        traces = self._load_all_traces(session_ids)
        if not traces:
            return ErrorSummary()

        error_traces = [t for t in traces if t.has_errors]
        error_messages: list[str] = []
        for trace in error_traces:
            for span in trace.spans:
                if span.status == "error" and span.attributes.get("error"):
                    error_messages.append(str(span.attributes["error"])[:100])

        # Top unique errors
        seen: dict[str, int] = {}
        for msg in error_messages:
            seen[msg] = seen.get(msg, 0) + 1
        top_errors = sorted(seen.keys(), key=lambda k: seen[k], reverse=True)[:5]

        return ErrorSummary(
            total_traces=len(traces),
            error_traces=len(error_traces),
            error_rate=len(error_traces) / len(traces) if traces else 0,
            top_errors=top_errors,
        )
