"""Trace and Span models for structured observability."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class Span(BaseModel):
    """A single unit of work within a trace (e.g. one node execution, one LLM call)."""

    span_id: str
    parent_span_id: Optional[str] = None
    name: str
    node_name: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    latency_ms: int = 0
    status: Literal["ok", "error", "cancelled"] = "ok"
    started_at: str = ""
    ended_at: Optional[str] = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class Trace(BaseModel):
    """A collection of spans representing one complete execution (session turn, workflow run)."""

    trace_id: str
    session_id: Optional[str] = None
    workflow_id: Optional[str] = None
    started_at: str = ""
    ended_at: Optional[str] = None
    spans: list[Span] = Field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return sum((s.tokens_in or 0) + (s.tokens_out or 0) for s in self.spans)

    @property
    def total_latency_ms(self) -> int:
        return sum(s.latency_ms for s in self.spans)

    @property
    def has_errors(self) -> bool:
        return any(s.status == "error" for s in self.spans)
