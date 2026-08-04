"""A 15-minute turn must not end with nothing to show for it.

A gateway turn against the codex CLI is bounded by ``cli_timeout``. That bound
is correct and this module does not change it. What it changes is what happens
when the bound is reached.

Two defects, both observed in a real gateway session that spent its full
configured 900s:

* ``_turn`` accumulates the agent items as they stream, then raises a timeout
  carrying only a message -- so every partial result is discarded. The user
  waited fifteen minutes and received a generic error.
* ``ask`` retries ``_turn`` after a session restart, and the deadline is
  computed *inside* ``_turn``. The second attempt therefore starts a fresh full
  budget, so one ask() can spend ``2 x cli_timeout``. With cli_timeout=900 that
  is half an hour for one message.
"""

from __future__ import annotations

import queue
import time

import pytest

from birkin.codex_session import (CodexAppServerSession,
                                  CodexSessionError, CodexTurnTimeout)


def _session(turn_timeout: float = 0.4,
             pending: tuple[str, ...] = ()) -> CodexAppServerSession:
    """A session wired for the turn loop only -- no codex binary involved.

    __init__ spawns a child process, which this test must not do; every
    attribute _turn reads is set explicitly instead.
    """
    s = CodexAppServerSession.__new__(CodexAppServerSession)
    s._notes = queue.Queue()
    s._thread_id = "thread-1"
    s._active_turn_id = "turn-1"
    s.turn_timeout = turn_timeout
    s.request_timeout = 5.0
    s.preamble = ""
    s._sent_preamble = True
    s._interrupted = False
    s._closed = False
    # _turn opens by DRAINING _notes of stale events, so anything queued
    # beforehand is thrown away. A real server emits items only after
    # turn/start is accepted, and the fixture has to do the same or it tests
    # nothing.
    def _request(method, params, timeout=None):
        if method == "turn/start":
            for piece in pending:
                s._notes.put(_item(piece))
        return {"turn": {"id": "turn-1"}}

    s.request = _request
    return s


def _item(text: str) -> dict:
    return {"method": "item/completed",
            "params": {"threadId": "thread-1", "turnId": "turn-1",
                       "item": {"type": "agent_message", "text": text}}}


class TestPartialOutputSurvivesTheTimeout:
    def test_the_timeout_carries_what_had_already_streamed(self) -> None:
        s = _session(turn_timeout=0.4,
                     pending=("첫 번째 분석 결과입니다.", "두 번째 항목."))
        with pytest.raises(CodexTurnTimeout) as caught:
            s._turn("분석해줘", None, None)
        partial = getattr(caught.value, "partial", "")
        assert "첫 번째 분석 결과입니다." in partial
        assert "두 번째 항목." in partial

    def test_a_timeout_with_nothing_streamed_carries_no_partial(self) -> None:
        s = _session(turn_timeout=0.3)
        with pytest.raises(CodexTurnTimeout) as caught:
            s._turn("hi", None, None)
        assert getattr(caught.value, "partial", "") == ""

    def test_the_message_still_names_the_budget_that_was_spent(self) -> None:
        s = _session(turn_timeout=0.3)
        with pytest.raises(CodexTurnTimeout) as caught:
            s._turn("hi", None, None)
        assert "timed out" in str(caught.value)


class TestOneAskSpendsOneBudget:
    def test_a_restart_retry_does_not_start_a_fresh_full_budget(self) -> None:
        """The observed bug: deadline lives inside _turn, so attempt two got
        another full cli_timeout. One message could cost 2 x the budget."""
        seen: list[float | None] = []

        def fake_turn(text, on_text, timeout):
            seen.append(timeout)
            if len(seen) == 1:
                raise CodexSessionError("codex process exited unexpectedly")
            return "second attempt answered"

        s = _session(turn_timeout=10.0)
        s.is_alive = lambda: True
        s.start = lambda: None
        s._lock = __import__("threading").RLock()
        s._turn = fake_turn
        assert s.ask("hello", None, 10.0) == "second attempt answered"
        assert len(seen) == 2
        # The retry must be given the REMAINING budget, never another full one.
        assert seen[1] is not None
        assert seen[1] < seen[0]

    def test_an_exhausted_budget_is_not_retried_at_all(self) -> None:
        def slow_turn(text, on_text, timeout):
            time.sleep(0.25)
            raise CodexSessionError("codex process exited unexpectedly")

        s = _session(turn_timeout=0.2)
        s.is_alive = lambda: True
        s.start = lambda: None
        s._lock = __import__("threading").RLock()
        s._turn = slow_turn
        with pytest.raises((CodexSessionError, CodexTurnTimeout)):
            s.ask("hello", None, 0.2)
