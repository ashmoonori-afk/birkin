"""Raw event model — records every LLM/tool interaction for compilation."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class TokenUsageRecord(BaseModel, frozen=True):
    """Token usage snapshot for an event."""

    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


class RawEvent(BaseModel):
    """A single interaction event to be compiled into memory.

    Every LLM call, tool call, user message, decision, or action
    is recorded as a RawEvent in the EventStore.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = Field(default_factory=lambda: dt.datetime.now(dt.timezone.utc).isoformat())
    session_id: str = ""
    event_type: Literal["llm_call", "tool_call", "user_message", "assistant_message", "decision", "action"] = (
        "llm_call"
    )
    provider: Optional[str] = None
    model: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    tokens: Optional[TokenUsageRecord] = None
    outcome: Literal["success", "error", "cancelled"] = "success"
