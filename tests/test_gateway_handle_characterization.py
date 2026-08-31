"""Characterization tests for Gateway.handle orchestration boundaries."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

import pytest

from birkin import store, transcripts
from birkin.gateway import core as gateway_core


class _Session:
    def __init__(self, events: list[str], *, reply: str = "reply") -> None:
        self.events = events
        self.reply = reply
        self.agent = SimpleNamespace(messages=[])

    def ask(
        self,
        text: str,
        on_text: Callable[[str], None] | None = None,
        **_kwargs: object,
    ) -> str:
        self.events.append("ask")
        self.agent.messages.append({"role": "user", "content": text})
        if on_text is not None:
            on_text("streamed")
        return self.reply

    def _prepare_cli_turn(self, text: str, **_kwargs: object) -> str:
        return text

    def _record_turn(self, *_args: object, **_kwargs: object) -> None:
        self.events.append("record")


class _WarmSession:
    def __init__(self, events: list[str], *, error: Exception | None = None) -> None:
        self.events = events
        self.error = error

    def ask(
        self,
        _text: str,
        on_text: Callable[[str], None] | None = None,
        **_kwargs: object,
    ) -> str:
        self.events.append("ask")
        if on_text is not None:
            on_text("streamed")
        if self.error is not None:
            raise self.error
        return "persistent reply"

    def close(self) -> None:
        pass


class _Pool:
    def __init__(self, session: _WarmSession, events: list[str]) -> None:
        self.session = session
        self.events = events

    def borrow(self, _key: tuple[str, str]) -> _WarmSession:
        self.events.append("borrow")
        return self.session

    def release(self, _key: tuple[str, str], _session: _WarmSession) -> None:
        self.events.append("release")


@pytest.fixture
def gateway_factory(monkeypatch):
    def make(cfg: dict[str, object] | None = None):
        events: list[str] = []
        session = _Session(events)
        monkeypatch.setattr(gateway_core, "build_session", lambda _cfg: session)
        gateway = gateway_core.Gateway(cfg or {"gateway_persistent": False})
        monkeypatch.setattr(
            store, "append_activity", lambda _text: events.append("activity")
        )
        monkeypatch.setattr(
            transcripts,
            "append_turn",
            lambda *_args, **_kwargs: events.append("transcript"),
        )
        monkeypatch.setattr(transcripts, "read_recent", lambda *_args: "")
        return gateway, session, events

    return make


def test_empty_input_stops_before_admission(gateway_factory) -> None:
    gateway, _session, events = gateway_factory()

    assert gateway.handle("http", "chat", "  \n ") == ""
    assert events == []


def test_untrusted_sender_stops_before_command_and_model(gateway_factory) -> None:
    gateway, _session, events = gateway_factory(
        {
            "gateway_persistent": False,
            "channels": {"kakao": {"allowed_sender_ids": ["owner"]}},
        }
    )

    assert (
        gateway.handle("kakao", "room", "/help", sender_id="intruder")
        == gateway_core.UNTRUSTED_CHANNEL_REPLY
    )
    assert events == []


def test_gateway_command_stops_before_model_turn(gateway_factory) -> None:
    gateway, _session, events = gateway_factory()

    assert gateway.handle("http", "chat", "/help") == gateway_core.gateway_help_text()
    assert events == []


def test_privileged_command_denial_stops_before_dispatch(gateway_factory) -> None:
    gateway, _session, events = gateway_factory(
        {"provider": "anthropic", "gateway_persistent": False}
    )

    reply = gateway.handle("telegram", "public", "/restart")

    assert "restricted" in reply.lower()
    assert events == []


def test_nonpersistent_model_turn_preserves_result_order(gateway_factory) -> None:
    gateway, _session, events = gateway_factory()

    assert gateway.handle("http", "chat", "hello") == "reply"
    assert events == ["ask", "activity", "transcript"]


def test_persistent_streaming_and_result_order(
    gateway_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway, _session, events = gateway_factory()
    gateway._persistent = True
    warm = _WarmSession(events)
    monkeypatch.setattr(gateway, "_claude_sessions", _Pool(warm, events))
    pieces: list[str] = []

    assert (
        gateway.handle("http", "chat", "hello", on_text=pieces.append)
        == "persistent reply"
    )
    assert pieces == ["streamed"]
    assert events == [
        "borrow",
        "ask",
        "activity",
        "record",
        "transcript",
        "release",
    ]


def test_exception_returns_before_result_effects_but_still_releases(
    gateway_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway, _session, events = gateway_factory()
    gateway._persistent = True
    warm = _WarmSession(events, error=RuntimeError("private detail"))
    monkeypatch.setattr(gateway, "_claude_sessions", _Pool(warm, events))

    assert gateway.handle("http", "chat", "hello") == gateway_core.TURN_ERROR_REPLY
    assert events == ["borrow", "ask", "release"]
