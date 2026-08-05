"""Mid-turn chat heartbeats must carry what the turn is actually doing.

A 26-minute gateway turn showed the user NOTHING in chat while 12 minutes of
real tool work ran. The session now reports that work through on_progress
(codex_session), but the gateway drops it on the floor: handle() never passes
the callback, and the telegram heartbeat renders only elapsed minutes.

Two contracts:

* handle() forwards on_progress to a session whose ask() accepts it, and
  silently omits it for one that does not -- the warm pool holds
  ClaudeStreamSession too, whose ask() has no such parameter, and a TypeError
  there would kill every claude-backed turn.
* the telegram heartbeat line includes the activity snapshot when one exists,
  so the user reads "도구 9회 실행" instead of a bare minute count.
"""

from __future__ import annotations

import threading

from birkin.gateway import core as gateway_core
from birkin.gateway.channels import telegram as tg


class _CodexLike:
    """ask() accepts on_progress, like CodexAppServerSession now does."""

    def __init__(self) -> None:
        self.seen_progress = "NOT PASSED"

    def ask(self, text, on_text=None, timeout=None, on_progress=None):
        self.seen_progress = on_progress
        if on_progress is not None:
            on_progress({"activity": 3, "streamed": 1,
                         "last_kind": "command_execution"})
        return "done"


class _ClaudeLike:
    """ask() with NO on_progress parameter, like ClaudeStreamSession."""

    def ask(self, text, on_text=None, timeout=None):
        return "done"


class TestGatewayForwardsProgress:
    def test_a_codex_like_session_receives_the_callback(self) -> None:
        sess = _CodexLike()
        seen: list[dict] = []
        reply = gateway_core.ask_session(sess, "hi", on_text=None,
                                         on_progress=seen.append)
        assert reply == "done"
        assert sess.seen_progress is not None
        assert sess.seen_progress != "NOT PASSED"
        assert seen and seen[-1]["activity"] == 3

    def test_a_claude_like_session_is_not_broken_by_it(self) -> None:
        """Passing on_progress blindly would TypeError claude-backed turns."""
        reply = gateway_core.ask_session(_ClaudeLike(), "hi", on_text=None,
                                         on_progress=lambda info: None)
        assert reply == "done"

    def test_no_callback_is_the_ordinary_case(self) -> None:
        assert gateway_core.ask_session(_CodexLike(), "hi",
                                        on_text=None) == "done"


class TestHeartbeatRendersActivity:
    def test_with_activity_the_line_names_the_work(self) -> None:
        holder = {"activity": 9, "streamed": 0,
                  "last_kind": "command_execution"}
        line = tg.heartbeat_text(elapsed_minutes=5, progress=holder)
        assert "5" in line
        assert "9" in line, "activity count missing from the heartbeat"

    def test_without_activity_it_reads_like_before(self) -> None:
        line = tg.heartbeat_text(elapsed_minutes=3, progress=None)
        assert "3" in line
        assert "작업 진행 중" in line

    def test_streamed_items_are_reported_too(self) -> None:
        line = tg.heartbeat_text(elapsed_minutes=1,
                                 progress={"activity": 4, "streamed": 2,
                                           "last_kind": "agent_message"})
        assert "2" in line

    def test_the_holder_updated_from_another_thread_is_read_safely(self) -> None:
        """on_progress fires on the turn thread; the pinger reads on its own."""
        holder: dict = {}
        stop = threading.Event()

        def writer() -> None:
            for i in range(200):
                holder.update({"activity": i, "streamed": 0,
                               "last_kind": "command_execution"})
            stop.set()

        t = threading.Thread(target=writer)
        t.start()
        while not stop.is_set():
            tg.heartbeat_text(elapsed_minutes=1,
                              progress=holder if holder else None)
        t.join(timeout=5)
        line = tg.heartbeat_text(elapsed_minutes=1, progress=holder)
        assert "199" in line
