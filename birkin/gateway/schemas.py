"""Request / response schemas for the gateway API."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from birkin import __version__

# --- Chat ---


class ChatRequest(BaseModel):
    """Payload for POST /api/chat."""

    session_id: Optional[str] = Field(
        default=None,
        description="Session to continue. A new session is created when omitted.",
    )
    message: str = Field(..., min_length=1, description="User message text.")
    provider: str = Field(default="anthropic", description="LLM provider name.")
    model: Optional[str] = Field(default=None, description="Model override.")


class ChatResponse(BaseModel):
    """Response from POST /api/chat."""

    session_id: str
    reply: str
    usage: dict[str, int] = Field(default_factory=dict)
    suggestions: list[dict] = Field(default_factory=list)


# --- Sessions ---


class SessionSummary(BaseModel):
    """Lightweight session listing."""

    id: str
    created_at: datetime
    message_count: int


class MessageOut(BaseModel):
    """A single message within a session."""

    role: str
    content: str


class SessionDetail(BaseModel):
    """Full session with messages."""

    id: str
    created_at: datetime
    messages: list[MessageOut]


# --- Health ---


class HealthResponse(BaseModel):
    """Response from GET /api/health."""

    status: str = "ok"
    version: str = __version__
