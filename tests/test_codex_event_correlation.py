"""Codex app-server replies must come from the active parent turn."""

from __future__ import annotations

import pytest

from birkin import codex_session
from birkin.codex_session import CodexAppServerSession

_TurnStartParams = dict[str, str | list[dict[str, str]]]


@pytest.mark.parametrize(
    ("foreign_thread", "foreign_turn"),
    [
        ("child-thread", "child-turn"),
        ("parent-thread", "stale-turn"),
    ],
)
def test_codex_turn_ignores_foreign_agent_completion(
    monkeypatch: pytest.MonkeyPatch,
    foreign_thread: str,
    foreign_turn: str,
) -> None:
    session = CodexAppServerSession()
    session._thread_id = "parent-thread"

    def request(
        method: str,
        params: _TurnStartParams | None = None,
        timeout: float | None = None,
    ) -> dict[str, dict[str, str]]:
        assert method == "turn/start"
        session._notes.put(
            {
                "method": "item/completed",
                "params": {
                    "threadId": foreign_thread,
                    "turnId": foreign_turn,
                    "item": {
                        "type": "agentMessage",
                        "text": "<analysis>unrelated child inventory</analysis>",
                    },
                },
            }
        )
        session._notes.put(
            {
                "method": "turn/completed",
                "params": {
                    "threadId": foreign_thread,
                    "turn": {"id": foreign_turn, "status": "completed"},
                },
            }
        )
        session._notes.put(
            {
                "method": "item/completed",
                "params": {
                    "threadId": "parent-thread",
                    "turnId": "parent-turn",
                    "item": {
                        "type": "agentMessage",
                        "text": "requested stock report",
                    },
                },
            }
        )
        session._notes.put(
            {
                "method": "turn/completed",
                "params": {
                    "threadId": "parent-thread",
                    "turn": {"id": "parent-turn", "status": "completed"},
                },
            }
        )
        return {"turn": {"id": "parent-turn"}}

    monkeypatch.setattr(session, "request", request)
    streamed: list[str] = []

    reply = session._turn("approved stock plan", streamed.append, timeout=2)

    assert reply == "requested stock report"
    assert streamed == ["requested stock report"]


def test_codex_turn_keeps_internal_context_out_of_user_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = CodexAppServerSession(preamble="You are birkin.")
    session._thread_id = "parent-thread"
    captured: dict = {}

    def request(method: str, params: dict | None = None, timeout=None) -> dict:
        assert method == "turn/start"
        captured.update(params or {})
        session._notes.put({
            "method": "turn/completed",
            "params": {
                "threadId": "parent-thread",
                "turn": {"id": "parent-turn", "status": "completed"},
            },
        })
        return {"turn": {"id": "parent-turn"}}

    monkeypatch.setattr(session, "request", request)

    session._turn("actual user message", None, timeout=2)

    assert captured["input"] == [
        {"type": "text", "text": "actual user message"}
    ]


def test_codex_thread_is_ephemeral_and_receives_developer_instructions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Process:
        stdout = None

        @staticmethod
        def poll() -> None:
            return None

    class ReaderThread:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def start(self) -> None:
            pass

    session = CodexAppServerSession(
        cwd="workspace", preamble="You are birkin.", startup_timeout=2,
    )
    starts: list[dict] = []

    def request(method: str, params: dict | None = None, timeout=None) -> dict:
        if method == "thread/start":
            starts.append(params or {})
            return {"thread": {"id": "thread-1"}}
        return {}

    monkeypatch.setattr(
        codex_session.subprocess, "Popen", lambda *a, **k: Process()
    )
    monkeypatch.setattr(codex_session.threading, "Thread", ReaderThread)
    monkeypatch.setattr(session, "request", request)
    monkeypatch.setattr(session, "_notify", lambda *a, **k: None)

    session.start()

    assert starts == [{
        "cwd": "workspace",
        "developerInstructions": "You are birkin.",
        "ephemeral": True,
    }]
