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

import json
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


def _started(kind: str) -> dict:
    return {"method": "item/started",
            "params": {"threadId": "t", "turnId": "turn-1",
                       "item": {"id": "item-1", "type": kind}}}


def _tool(command: str) -> dict:
    """A completed tool item: real work that streams no agent text."""
    return {"method": "item/completed",
            "params": {"threadId": "t", "turnId": "turn-1",
                       "item": {"type": "command_execution",
                                "command": command}}}


def _child_tool(command: str) -> dict:
    """A multi-agent item uses its child turn id in the parent thread."""
    return {"method": "item/completed",
            "params": {"threadId": "t", "turnId": "child-turn",
                       "item": {"type": "commandExecution",
                                "command": command}}}


def _child_agent(text: str) -> dict:
    return {"method": "item/completed",
            "params": {"threadId": "t", "turnId": "child-turn",
                       "item": {"type": "agentMessage", "text": text}}}


def _mcp(method: str, *, turn_id: str = "turn-1",
         status: str = "inProgress") -> dict:
    return {"method": method,
            "params": {"threadId": "t", "turnId": turn_id,
                       "item": {"id": "mcp-item-1", "type": "mcpToolCall",
                                "server": "birkin", "tool": "work_item_request",
                                "status": status, "arguments": {"private": True}}}}


def _done() -> dict:
    return {"method": "turn/completed",
            "params": {"threadId": "t",
                       "turn": {"id": "turn-1", "status": "completed"}}}


class TestOnProgressSeesTheWork:
    def test_parent_mcp_identity_and_schema_status_are_reported(self) -> None:
        seen: list[dict] = []
        s = _session(pending=(
            _mcp("item/started"),
            _mcp("item/completed", status="completed"),
            _done(),
        ))

        s._turn("hi", None, None, on_progress=seen.append)

        tools = [progress["mcp_tool_call"] for progress in seen
                 if "mcp_tool_call" in progress]
        assert tools == [
            {"event": "item/started", "item_id": "mcp-item-1",
             "server": "birkin", "name": "work_item_request",
             "status": "inProgress"},
            {"event": "item/completed", "item_id": "mcp-item-1",
             "server": "birkin", "name": "work_item_request",
             "status": "completed"},
        ]
        assert "private" not in str(tools)

    def test_failed_mcp_status_is_preserved_without_result(self) -> None:
        seen: list[dict] = []
        failed = _mcp("item/completed", status="failed")
        failed["params"]["item"]["result"] = {"content": "private result"}
        s = _session(pending=(failed, _done()))

        s._turn("hi", None, None, on_progress=seen.append)

        tool = next(progress["mcp_tool_call"] for progress in seen
                    if "mcp_tool_call" in progress)
        assert tool["status"] == "failed"
        assert "private result" not in str(tool)

    def test_failed_office_mcp_reports_only_safe_locator_shapes(self) -> None:
        marker = "SECRET_MARKER"
        seen: list[dict] = []
        failed = _mcp("item/completed", status="failed")
        item = failed["params"]["item"]
        item.update({
            "tool": "office_job_request",
            "arguments": {
                "source": {"uri": f"C:/private/{marker}.docx"},
                "operations": [
                    {"locator": {"format": "docx", "index": 1},
                     "value": marker},
                    {"locator": {"kind": "paragraph", "index": 0,
                                 marker: marker}, "value": marker},
                ],
            },
            "result": {"content": [{"type": "text", "text": json.dumps({
                "error": {"code": "PRECONDITION_FAILED",
                          "stage": "preview", "message": marker},
            })}]},
        })
        s = _session(pending=(failed, _done()))

        s._turn("hi", None, None, on_progress=seen.append)

        tool = next(progress["mcp_tool_call"] for progress in seen
                    if "mcp_tool_call" in progress)
        assert tool["diagnostic"] == {
            "operation_count": 2,
            "locator_shapes": ["public_docx_positive_index",
                               "native_or_extra_locator"],
            "error_code": "PRECONDITION_FAILED",
            "error_stage": "preview",
        }
        assert marker not in str(tool)

    def test_failed_office_mcp_without_operations_keeps_safe_error(self) -> None:
        seen: list[dict] = []
        failed = _mcp("item/completed", status="failed")
        item = failed["params"]["item"]
        item.update({
            "tool": "office_job_request",
            "arguments": {"request": "SECRET_MARKER"},
            "error": {"message": json.dumps({
                "error": {"code": "INVALID_INPUT", "stage": "plan"},
            })},
        })
        s = _session(pending=(failed, _done()))

        s._turn("hi", None, None, on_progress=seen.append)

        diagnostic = next(progress["mcp_tool_call"]["diagnostic"]
                          for progress in seen if "mcp_tool_call" in progress)
        assert diagnostic == {
            "operation_count": None,
            "locator_shapes": [],
            "error_code": "INVALID_INPUT",
            "error_stage": "plan",
        }
        assert "SECRET_MARKER" not in str(diagnostic)

    def test_failed_office_mcp_ignores_oversized_and_invalid_error_fields(
        self,
    ) -> None:
        seen: list[dict] = []
        failed = _mcp("item/completed", status="failed")
        item = failed["params"]["item"]
        item.update({
            "tool": "office_job_request",
            "arguments": {},
            "result": {"content": [{"type": "text", "text": "x" * 16_385}]},
            "error": {"message": json.dumps({
                "error": {"code": [], "stage": {}},
            })},
        })
        s = _session(pending=(failed, _done()))

        assert s._turn("hi", None, None, on_progress=seen.append) == ""
        diagnostic = next(progress["mcp_tool_call"]["diagnostic"]
                          for progress in seen if "mcp_tool_call" in progress)
        assert diagnostic == {"operation_count": None, "locator_shapes": []}

    def test_failed_office_mcp_json_recursion_does_not_kill_turn(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        failed = _mcp("item/completed", status="failed")
        failed["params"]["item"].update({
            "tool": "office_job_request",
            "arguments": {},
            "error": {"message": "small json candidate"},
        })
        monkeypatch.setattr(
            "birkin.codex_session.json.loads",
            lambda _text: (_ for _ in ()).throw(RecursionError()),
        )
        seen: list[dict] = []
        s = _session(pending=(failed, _done()))

        assert s._turn("hi", None, None, on_progress=seen.append) == ""
        assert any("mcp_tool_call" in progress for progress in seen)

    def test_child_mcp_is_liveness_only_not_a_parent_tool(self) -> None:
        seen: list[dict] = []
        s = _session(pending=(
            _mcp("item/completed", turn_id="child-turn", status="completed"),
            _done(),
        ))

        s._turn("hi", None, None, on_progress=seen.append)

        assert seen[-1]["activity"] == 1
        assert all("mcp_tool_call" not in progress for progress in seen)

    def test_child_and_foreign_office_failures_do_not_leak_diagnostics(self) -> None:
        seen: list[dict] = []
        child = _mcp("item/completed", turn_id="child-turn", status="failed")
        child["params"]["item"].update({
            "tool": "office_job_request",
            "arguments": {"operations": [{"SECRET_MARKER": True}]},
        })
        foreign = _mcp("item/completed", status="failed")
        foreign["params"]["threadId"] = "foreign-thread"
        foreign["params"]["item"].update(child["params"]["item"])
        s = _session(pending=(child, foreign, _done()))

        s._turn("hi", None, None, on_progress=seen.append)

        assert all("mcp_tool_call" not in progress for progress in seen)
        assert "SECRET_MARKER" not in str(seen)

    def test_started_reasoning_is_visible_before_it_completes(self) -> None:
        seen: list[dict] = []
        s = _session(pending=(_started("reasoning"), _done()))

        s._turn("hi", None, None, on_progress=seen.append)

        assert seen
        assert seen[0]["activity"] == 0
        assert seen[0]["active_kind"] == "reasoning"

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

    def test_child_turn_items_count_as_current_thread_activity(self) -> None:
        seen: list[dict] = []
        s = _session(pending=(_child_tool("kaggle competitions files"),
                              _done()))

        s._turn("hi", None, None, on_progress=seen.append)

        assert seen[-1]["activity"] == 1
        assert seen[-1]["last_kind"] == "commandExecution"

    def test_foreign_thread_items_stay_ignored(self) -> None:
        seen: list[dict] = []
        foreign = _child_tool("unrelated")
        foreign["params"]["threadId"] = "another-thread"
        s = _session(pending=(foreign, _done()))

        s._turn("hi", None, None, on_progress=seen.append)

        assert seen == []

    def test_child_agent_text_stays_out_of_parent_reply(self) -> None:
        seen: list[dict] = []
        streamed: list[str] = []
        s = _session(pending=(
            _child_agent("child inventory"),
            _agent("parent answer"),
            _done(),
        ))

        reply = s._turn("hi", streamed.append, None,
                        on_progress=seen.append)

        assert reply == "parent answer"
        assert streamed == ["parent answer"]
        assert seen[-1]["activity"] == 2
        assert seen[-1]["streamed"] == 1

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
