"""Long codex turns: silence is the failure, not the clock.

A gateway turn was bounded by wall clock -- cli_timeout seconds from
turn/start, regardless of what the model was doing. A long research turn that
streamed steadily was killed mid-work at exactly the moment it was healthiest,
which is the failure the user actually reported: work taking 15+ minutes kept
dying at the timeout.

The bound is now an IDLE window. A turn that keeps producing -- items, tool
activity -- runs as long as the work takes, with a heartbeat in the server log
so a human can see it is alive. Only silence for the WHOLE window means codex
is wedged, and a wedged process is still reaped: removing the bound entirely
would trade "long turns die" for "a dead codex holds the gateway forever".
"""

from __future__ import annotations

import queue
import threading
import time

import pytest

from birkin.codex_session import (CodexAppServerSession, CodexSessionError,
                                  CodexTurnTimeout)


def _item(text: str) -> dict:
    return {"method": "item/completed",
            "params": {"threadId": "thread-1", "turnId": "turn-1",
                       "item": {"type": "agent_message", "text": text}}}


def _completed() -> dict:
    return {"method": "turn/completed",
            "params": {"threadId": "thread-1",
                       "turn": {"id": "turn-1", "status": "completed"}}}


def _session(turn_timeout: float = 0.4, pending: tuple = (),
             heartbeat: float = 60.0) -> CodexAppServerSession:
    """A session wired for the turn loop only -- no codex binary involved."""
    s = CodexAppServerSession.__new__(CodexAppServerSession)
    s._notes = queue.Queue()
    s._thread_id = "thread-1"
    s._active_turn_id = "turn-1"
    s.turn_timeout = turn_timeout
    s.request_timeout = 5.0
    s.heartbeat_interval = heartbeat
    s.preamble = ""
    s._sent_preamble = True
    s._interrupted = False
    s._closed = False
    s._lock = threading.RLock()

    def _request(method, params, timeout=None):
        if method == "turn/start":
            for piece in pending:
                s._notes.put(_item(piece))
        return {"turn": {"id": "turn-1"}}

    s.request = _request
    return s


class TestActivityKeepsTheTurnAlive:
    def test_steady_progress_outlives_the_idle_window(self) -> None:
        """The reported case, scaled down: total time is 3x the window.

        Four items spaced 0.3s apart against a 0.5s window. No single gap
        reaches the window, so the turn must complete -- under the wall-clock
        rule it died after 0.5s with three items still coming.
        """
        s = _session(turn_timeout=0.5)

        def feed() -> None:
            for i in range(4):
                time.sleep(0.3)
                s._notes.put(_item(f"piece {i}"))
            time.sleep(0.3)
            s._notes.put(_completed())

        feeder = threading.Thread(target=feed, daemon=True)
        feeder.start()
        assert s._turn("go", None, None) == "piece 3"
        feeder.join(timeout=5)

    def test_silence_for_the_whole_window_still_reaps_the_turn(self) -> None:
        """No bound at all would leave a wedged codex holding the gateway."""
        s = _session(turn_timeout=0.3)
        began = time.monotonic()
        with pytest.raises(CodexTurnTimeout) as caught:
            s._turn("go", None, None)
        assert "timed out" in str(caught.value)
        assert time.monotonic() - began < 3.0

    def test_the_window_measures_from_the_last_activity(self) -> None:
        s = _session(turn_timeout=0.4, pending=("one piece",))
        with pytest.raises(CodexTurnTimeout) as caught:
            s._turn("go", None, None)
        assert "one piece" in caught.value.partial


class TestHeartbeat:
    def test_a_long_turn_reports_it_is_alive(self, capsys) -> None:
        s = _session(turn_timeout=5.0, heartbeat=0.2)

        def feed() -> None:
            time.sleep(0.7)
            s._notes.put(_completed())

        threading.Thread(target=feed, daemon=True).start()
        s._turn("go", None, None)
        assert "still working" in capsys.readouterr().out

    def test_a_quick_turn_stays_quiet(self, capsys) -> None:
        """A heartbeat on every two-second turn is log spam, not a signal."""
        s = _session(turn_timeout=5.0, heartbeat=60.0, pending=("hi",))

        def feed() -> None:
            time.sleep(0.1)
            s._notes.put(_completed())

        threading.Thread(target=feed, daemon=True).start()
        s._turn("go", None, None)
        assert "still working" not in capsys.readouterr().out


class TestPartialOutputSurvivesTheTimeout:
    def test_the_timeout_carries_what_had_already_streamed(self) -> None:
        s = _session(turn_timeout=0.4,
                     pending=("첫 번째 분석 결과입니다.", "두 번째 항목."))
        with pytest.raises(CodexTurnTimeout) as caught:
            s._turn("분석해줘", None, None)
        assert "첫 번째 분석 결과입니다." in caught.value.partial
        assert "두 번째 항목." in caught.value.partial

    def test_a_timeout_with_nothing_streamed_carries_no_partial(self) -> None:
        s = _session(turn_timeout=0.3)
        with pytest.raises(CodexTurnTimeout) as caught:
            s._turn("hi", None, None)
        assert getattr(caught.value, "partial", "") == ""


class TestRetryIsBoundedByRestartsNotWallClock:
    def test_a_restart_retry_gets_the_same_idle_window(self) -> None:
        """The budget measures SILENCE, so the retry is not handed a shrunk
        window for the time the first attempt spent doing real work.
        Runaway retries are prevented by counting restarts (exactly one),
        not by shrinking the clock."""
        seen: list = []

        def fake_turn(text, on_text, timeout):
            seen.append(timeout)
            if len(seen) == 1:
                raise CodexSessionError("codex process exited unexpectedly")
            return "second attempt answered"

        s = _session(turn_timeout=10.0)
        s.is_alive = lambda: True
        s.start = lambda: None
        s._turn = fake_turn
        assert s.ask("hello", None, 10.0) == "second attempt answered"
        assert seen == [10.0, 10.0]

    def test_a_second_death_is_not_retried_again(self) -> None:
        calls: list = []

        def dying_turn(text, on_text, timeout):
            calls.append(timeout)
            raise CodexSessionError("codex process exited unexpectedly")

        s = _session(turn_timeout=10.0)
        s.is_alive = lambda: True
        s.start = lambda: None
        s._turn = dying_turn
        with pytest.raises(CodexSessionError):
            s.ask("hello", None, 10.0)
        assert len(calls) == 2
