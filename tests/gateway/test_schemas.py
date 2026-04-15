"""Tests for gateway schema validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from birkin.gateway.schemas import ChatRequest, ChatResponse, HealthResponse, SessionSummary


class TestChatRequest:
    def test_minimal(self):
        req = ChatRequest(message="hello")
        assert req.message == "hello"
        assert req.session_id is None
        assert req.provider == "anthropic"

    def test_with_session(self):
        req = ChatRequest(message="hi", session_id="abc123")
        assert req.session_id == "abc123"

    def test_empty_message_rejected(self):
        with pytest.raises(ValidationError):
            ChatRequest(message="")


class TestChatResponse:
    def test_roundtrip(self):
        resp = ChatResponse(session_id="s1", reply="ok")
        assert resp.model_dump() == {
            "session_id": "s1",
            "reply": "ok",
            "usage": {},
        }


class TestHealthResponse:
    def test_defaults(self):
        h = HealthResponse()
        assert h.status == "ok"
        assert h.version == "0.1.0"
