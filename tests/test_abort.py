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


def test_listen_for_esc_noop_off_tty():
    # pytest captures stdin (not a TTY) -> a null listener, stop() is safe.
    listener = abortkey.listen_for_esc(lambda: None)
    listener.stop()
    assert isinstance(listener, abortkey._NullListener)


def test_session_has_clear_abort_event(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config, runtime
    config.save_config({**config.DEFAULT_CONFIG, "provider": "claude-cli"})
    s = runtime.build_session(config.load_config())
    assert isinstance(s.abort, threading.Event) and not s.abort.is_set()
