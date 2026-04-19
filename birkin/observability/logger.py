"""Structured logger — create and manage traces and spans."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Optional

from birkin.observability.trace import Span, Trace


class StructuredLogger:
    """Creates and manages traces with nested spans.

    Usage::

        logger = StructuredLogger()
        trace = logger.start_trace(session_id="s1")
        span = logger.start_span(trace, "llm_call", provider="anthropic")
        # ... do work ...
        logger.end_span(span, tokens_in=100, tokens_out=50)
        logger.end_trace(trace)
    """

    @staticmethod
    def start_trace(
        *,
        session_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
    ) -> Trace:
        """Begin a new trace."""
        return Trace(
            trace_id=str(uuid.uuid4()),
            session_id=session_id,
            workflow_id=workflow_id,
            started_at=dt.datetime.now(dt.UTC).isoformat(),
        )

    @staticmethod
    def start_span(
        trace: Trace,
        name: str,
        *,
        parent: Optional[Span] = None,
        node_name: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Span:
        """Begin a new span within a trace."""
        span = Span(
            span_id=str(uuid.uuid4()),
            parent_span_id=parent.span_id if parent else None,
            name=name,
            node_name=node_name,
            provider=provider,
            model=model,
            started_at=dt.datetime.now(dt.UTC).isoformat(),
        )
        trace.spans.append(span)
        return span

    @staticmethod
    def end_span(span: Span, **attrs: Any) -> None:
        """Finalize a span with timing and optional attributes.

        Common attrs: tokens_in, tokens_out, status, error.
        """
        span.ended_at = dt.datetime.now(dt.UTC).isoformat()

        # Calculate latency from timestamps
        if span.started_at and span.ended_at:
            start = dt.datetime.fromisoformat(span.started_at)
            end = dt.datetime.fromisoformat(span.ended_at)
            span.latency_ms = int((end - start).total_seconds() * 1000)

        for key, value in attrs.items():
            if hasattr(span, key):
                setattr(span, key, value)
            else:
                span.attributes[key] = value

    @staticmethod
    def end_trace(trace: Trace) -> None:
        """Finalize a trace."""
        trace.ended_at = dt.datetime.now(dt.UTC).isoformat()
