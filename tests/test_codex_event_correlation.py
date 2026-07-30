"""Codex app-server replies must come from the active parent turn."""

from __future__ import annotations

import pytest

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
