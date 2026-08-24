"""Esc-to-abort: agent loop interrupt, CLI subprocess kill, listener no-op."""

from __future__ import annotations

import sys
import threading
import time

from birkin import abortkey
from birkin.agent import Agent


class _Reg:
    def specs(self):
        return []

    def execute(self, name, tool_input):
        class _R:
            content = "ok"
            is_error = False
        return _R()


def test_agent_aborts_before_first_turn():
    class _Client:
        def complete(self, **kw):
            raise AssertionError("LLM must not be called when pre-aborted")
    a = threading.Event()
    a.set()
    out = Agent(client=_Client(), system="", registry=_Reg()).run("hi", abort=a)
    assert "aborted" in out.lower()


def test_agent_abort_stops_after_a_tool_turn():
    calls = {"n": 0}
    a = threading.Event()

    class _Client:
        def complete(self, **kw):
            calls["n"] += 1
            assert kw.get("abort") is a          # abort threaded into the client
            if calls["n"] == 1:
                return {"content": [{"type": "tool_use", "id": "t1",
                                     "name": "noop", "input": {}}],
                        "stop_reason": "tool_use"}
            raise AssertionError("turn 2 should be skipped by abort")

    class _AbortingReg(_Reg):
        def execute(self, name, tool_input):
            a.set()                              # a tool sets abort mid-run
            return super().execute(name, tool_input)

    out = Agent(client=_Client(), system="", registry=_AbortingReg()).run("do", abort=a)
    assert calls["n"] == 1 and "aborted" in out.lower()


def test_parallel_abort_returns_promptly_with_valid_history():
    long_started = threading.Event()
    release_long = threading.Event()
    long_finished = threading.Event()
    returned = threading.Event()
    abort = threading.Event()
    output = []

    calls = [
        {"type": "tool_use", "id": "long", "name": "web_fetch",
         "input": {"wait": True}},
        {"type": "tool_use", "id": "quick", "name": "web_fetch", "input": {}},
    ]

    class _Client:
        provider = "anthropic"

        def __init__(self):
            self.calls = 0

        def complete(self, **kw):
            self.calls += 1
            if self.calls == 1:
                return {"content": calls, "stop_reason": "tool_use"}
            raise AssertionError("abort must prevent another model turn")

    class _ParallelReg(_Reg):
        def execute(self, name, tool_input):
            if tool_input.get("wait"):
                long_started.set()
                try:
                    assert release_long.wait(timeout=10)
                finally:
                    long_finished.set()
            return super().execute(name, tool_input)

    agent = Agent(client=_Client(), system="", registry=_ParallelReg())

    def run_agent():
        try:
            output.append(agent.run("fetch", abort=abort))
        finally:
            returned.set()

    runner = threading.Thread(target=run_agent, name="parallel-abort-test")
    runner.start()
    assert long_started.wait(timeout=2)

    started = time.monotonic()
    abort.set()
    did_return = False
    try:
        did_return = returned.wait(timeout=4)
        elapsed = time.monotonic() - started
    finally:
        release_long.set()
        assert long_finished.wait(timeout=2)
        runner.join(timeout=2)

    assert not runner.is_alive()
    assert did_return, "parallel abort waited for the running tool"
    assert elapsed < 4
    assert output and "aborted" in output[0].lower()
    tool_uses = [
        block for message in agent.messages
        for block in message["content"] if block.get("type") == "tool_use"
    ]
    tool_results = [
        block for message in agent.messages
        for block in message["content"] if block.get("type") == "tool_result"
    ]
    assert len(tool_results) == len(calls)
    assert [block["tool_use_id"] for block in tool_results] == [
        block["id"] for block in tool_uses
    ]
    assert tool_results[0]["content"] == "aborted"
    assert tool_results[0]["is_error"] is True


def test_agent_no_abort_runs_normally():
    class _Client:
        def complete(self, **kw):
            return {"content": [{"type": "text", "text": "hello"}],
                    "stop_reason": "end_turn"}
    out = Agent(client=_Client(), system="", registry=_Reg()).run("hi")
    assert out == "hello"


def test_run_cli_capture_kills_on_abort():
    from birkin.llm import LLMClient
    c = LLMClient(provider="local-cli", model="", api_key="cli", base_url="",
                  cli_timeout=30)
    a = threading.Event()
    threading.Timer(0.2, a.set).start()
    t0 = time.monotonic()
    out, err, timed_out, aborted = c._run_cli_capture(
        [sys.executable, "-c", "import time; time.sleep(10)"], "", a)
    elapsed = time.monotonic() - t0
    assert aborted is True and timed_out is False
    assert elapsed < 6        # killed promptly, not after the 10s sleep


def test_run_cli_capture_normal_completes():
    from birkin.llm import LLMClient
    c = LLMClient(provider="local-cli", model="", api_key="cli", base_url="",
                  cli_timeout=30)
    out, err, timed_out, aborted = c._run_cli_capture(
        [sys.executable, "-c", "print('hi there')"], "", None)
    assert "hi there" in out and not timed_out and not aborted


def test_listen_for_interrupt_noop_off_tty():
    # pytest captures stdin (not a TTY) -> a null listener, stop() is safe.
    listener = abortkey.listen_for_interrupt(lambda: None)
    listener.stop()
    assert isinstance(listener, abortkey._NullListener)
    assert listener.pending_line == ""


def _bare_base():
    # Build a _Base without starting its reader thread, to unit-test _handle.
    obj = object.__new__(abortkey._Base)
    obj._fired = False
    obj._buf = []
    obj.pending_line = ""
    obj._on_interrupt = lambda: None
    return obj


def test_handle_typing_then_enter_carries_line():
    fired = {"n": 0}
    obj = _bare_base()
    obj._on_interrupt = lambda: fired.__setitem__("n", fired["n"] + 1)
    for c in "fix the bug":
        obj._handle(c)
    obj._handle("\r")                       # Enter -> interrupt + carry
    assert obj.pending_line == "fix the bug" and obj._fired and fired["n"] == 1


def test_handle_esc_discards_buffer():
    obj = _bare_base()
    obj._buf = list("half typed")
    obj._handle("\x1b")                     # Esc -> interrupt, no carry
    assert obj.pending_line == "" and obj._fired


def test_handle_backspace_edits_buffer():
    obj = _bare_base()
    obj._buf = list("abc")
    obj._handle("\x7f")
    assert obj._buf == list("ab") and not obj._fired


def test_handle_ignores_after_fired():
    obj = _bare_base()
    obj._handle("\r")                       # fires
    obj._handle("x")                        # ignored once fired
    assert obj._buf == [] and obj.pending_line == ""


def test_session_has_clear_abort_event(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config, runtime
    config.save_config({**config.DEFAULT_CONFIG, "provider": "claude-cli"})
    s = runtime.build_session(config.load_config())
    assert isinstance(s.abort, threading.Event) and not s.abort.is_set()
