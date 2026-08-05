"""A long codex turn must be observable while it runs, and legible when it dies.

A real gateway turn ran 26.7 minutes: ~12 minutes of genuine tool work, then a
wedged shell subprocess, then a correct reap after 900s of silence. The user
saw nothing in chat the whole time, and the timeout said only "timed out" --
12 minutes of tool activity left no trace anywhere a human looks.

Two contracts fix that, both on the session (the chat wiring builds on them):

* ``on_progress`` -- called as activity happens, with what KIND of activity.
  Tool events are activity even though they stream no agent text; that is
  exactly the turn shape that showed "0 item(s) streamed" for 25 heartbeats.
* the timeout names what the turn did before it went quiet, so a failure
  reads "9 tool events, quiet for the last 900s" instead of a bare timeout.

Everything here drives the real _turn loop through the same emit-on-turn/start
fixture the budget tests use. No sleeps: activity is counted, never timed.
"""

from __future__ import annotations

import queue
import threading

import pytest

from birkin.codex_session import CodexAppServerSession, CodexTurnTimeout


def _session(turn_timeout: float = 0.4, pending: tuple[dict, ...] = ()):
    s = CodexAppServerSession.__new__(CodexAppServerSession)
    s._notes = queue.Queue()
    s._thread_id = "t"
    s._active_turn_id = "turn-1"
    s.turn_timeout = turn_timeout
    s.request_timeout = 5.0
    s.heartbeat_interval = 3600.0          # print path stays out of the way
    s.preamble = ""
    s._sent_preamble = True
    s._interrupted = False
    s._closed = False
    s._lock = threading.RLock()

    def _request(method, params, timeout=None):
        if method == "turn/start":
            for note in pending:
                s._notes.put(note)
        return {"turn": {"id": "turn-1"}}

    s.request = _request
    return s


def _agent(text: str) -> dict:
    return {"method": "item/completed",
            "params": {"threadId": "t", "turnId": "turn-1",
                       "item": {"type": "agent_message", "text": text}}}


def _tool(command: str) -> dict:
    """A completed tool item: real work that streams no agent text."""
    return {"method": "item/completed",
            "params": {"threadId": "t", "turnId": "turn-1",
                       "item": {"type": "command_execution",
                                "command": command}}}


def _done() -> dict:
    return {"method": "turn/completed",
            "params": {"threadId": "t",
                       "turn": {"id": "turn-1", "status": "completed"}}}


class TestOnProgressSeesTheWork:
    def test_agent_messages_are_reported(self) -> None:
        seen: list[dict] = []
        s = _session(pending=(_agent("hello"), _done()))
        s._turn("hi", None, None, on_progress=seen.append)
        assert seen, "on_progress was never called"
        assert seen[-1]["streamed"] == 1

    def test_tool_events_count_as_activity_without_streaming(self) -> None:
        """The 26-minute turn's exact shape: work, but no agent text."""
        seen: list[dict] = []
        s = _session(pending=(_tool("pip install x"), _tool("pytest -q"),
                              _done()))
        s._turn("hi", None, None, on_progress=seen.append)
        last = seen[-1]
        assert last["activity"] >= 2
        assert last["streamed"] == 0
        assert last["last_kind"] == "command_execution"

    def test_a_raising_callback_cannot_kill_the_turn(self) -> None:
        def boom(_info: dict) -> None:
            raise RuntimeError("observer bug")

        s = _session(pending=(_agent("answer"), _done()))
        assert s._turn("hi", None, None, on_progress=boom) == "answer"

    def test_no_callback_is_the_ordinary_case(self) -> None:
        s = _session(pending=(_agent("answer"), _done()))
        assert s._turn("hi", None, None) == "answer"

    def test_cyber_access_block_is_held_for_the_scoped_retry(self) -> None:
        blocked = (
            "Trusted Access for Cyber: https://chatgpt.com/cyber"
        )
        streamed: list[str] = []
        s = _session(pending=(_agent(blocked), _done()))

        assert s._turn("hi", streamed.append, None) == blocked
        assert streamed == []


class TestAskPlumbsItThrough:
    def test_ask_forwards_on_progress(self) -> None:
        seen: list[dict] = []
        s = _session(pending=(_agent("ok"), _done()))
        s.is_alive = lambda: True
        s.start = lambda: None
        assert s.ask("hi", on_progress=seen.append) == "ok"
        assert seen and seen[-1]["streamed"] == 1


class TestTheTimeoutIsLegible:
    def test_it_names_the_activity_that_preceded_the_silence(self) -> None:
        s = _session(turn_timeout=0.3,
                     pending=(_tool("git clone big-repo"),
                              _tool("run the scan")))
        with pytest.raises(CodexTurnTimeout) as caught:
            s._turn("hi", None, None)
        message = str(caught.value)
        assert "2" in message and "event" in message, message

    def test_a_turn_that_never_worked_says_so_plainly(self) -> None:
        s = _session(turn_timeout=0.3)
        with pytest.raises(CodexTurnTimeout) as caught:
            s._turn("hi", None, None)
        assert "without progress" in str(caught.value)
