"""Gateway latency fixes (hermes-comparison §6): clean hooks, thinking knob,
token-delta streaming, Telegram edit-streaming, pre-warmed spare."""

from __future__ import annotations

import json

from birkin.claude_session import ClaudeStreamSession
from birkin.gateway.channels.telegram import _Streamer


# -- ClaudeStreamSession: settings file / env / argv -------------------------

def test_build_argv_settings_and_partial_messages():
    s = ClaudeStreamSession(settings={"disableAllHooks": True})
    argv = s._build_argv()
    assert "--include-partial-messages" in argv
    i = argv.index("--settings")
    settings_path = argv[i + 1]
    data = json.loads(open(settings_path, encoding="utf-8").read())
    assert data == {"disableAllHooks": True}
    s.close()
    import os
    assert not os.path.exists(settings_path)   # temp file cleaned up


def test_no_settings_flag_without_overrides():
    s = ClaudeStreamSession()
    assert "--settings" not in s._build_argv()
    s.close()


def test_child_env_merges_env_extra():
    s = ClaudeStreamSession(env_extra={"MAX_THINKING_TOKENS": 0})
    assert s.child_env()["MAX_THINKING_TOKENS"] == "0"
    s.close()


# -- _turn: token deltas stream once, assistant event stays silent -----------

def _ev(obj) -> tuple[str, str]:
    return ("out", json.dumps(obj))


def test_turn_streams_deltas_without_duplication(monkeypatch):
    # _turn drains stale events BEFORE sending, so the stubbed _send must
    # inject this turn's events at send time (as the real process would).
    s = ClaudeStreamSession()

    def fake_send(text):
        for piece in ("he", "llo"):
            s._q.put(_ev({"type": "stream_event",
                          "event": {"type": "content_block_delta",
                                    "delta": {"type": "text_delta",
                                              "text": piece}}}))
        s._q.put(_ev({"type": "assistant",
                      "message": {"content": [{"type": "text",
                                               "text": "hello"}]}}))
        s._q.put(_ev({"type": "result", "result": "hello"}))
    monkeypatch.setattr(s, "_send", fake_send)
    got: list[str] = []
    out = s._turn("hi", got.append, timeout=5)
    assert out == "hello"
    assert got == ["he", "llo"]       # deltas only — no duplicated full text


def test_turn_falls_back_to_assistant_event_when_no_deltas(monkeypatch):
    s = ClaudeStreamSession()

    def fake_send(text):
        s._q.put(_ev({"type": "assistant",
                      "message": {"content": [{"type": "text",
                                               "text": "hi!"}]}}))
        s._q.put(_ev({"type": "result", "result": "hi!"}))
    monkeypatch.setattr(s, "_send", fake_send)
    got: list[str] = []
    assert s._turn("hi", got.append, timeout=5) == "hi!"
    assert got == ["hi!"]


# -- Telegram _Streamer -------------------------------------------------------

class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _streamer(sends, edits, clock, **kw):
    return _Streamer(lambda t: (sends.append(t), "m1")[1],
                     lambda mid, t: (edits.append((mid, t)), True)[1],
                     clock=clock, **kw)


def test_streamer_first_flush_waits_for_min_chars():
    sends, edits, clock = [], [], _Clock()
    st = _streamer(sends, edits, clock, min_first=10)
    st.feed("short")                 # 5 chars < min_first -> no bubble yet
    assert sends == []
    st.feed(" and more text")
    assert sends == ["short and more text"]
    assert st.message_id == "m1"


def test_streamer_throttles_edits():
    sends, edits, clock = [], [], _Clock()
    st = _streamer(sends, edits, clock, min_first=1, interval=1.5)
    st.feed("first piece arrives")
    st.feed(" immediate follow-up")          # within interval -> buffered only
    assert edits == []
    clock.t = 2.0
    st.feed(" later piece")                  # past interval -> one edit
    assert len(edits) == 1
    assert edits[0][1].endswith("later piece")


def test_streamer_saturates_at_cap_and_send_failure_is_silent():
    sends, edits, clock = [], [], _Clock()
    st = _streamer(sends, edits, clock, min_first=1, cap=10)
    st.feed("0123456789ABC")                 # over cap on first flush
    assert sends and sends[0].startswith("0123456789")
    clock.t = 10.0
    st.feed("more")                          # saturated -> no further edits
    assert edits == []
    # send failure -> stays silent, never raises
    st2 = _Streamer(lambda t: None, lambda m, t: True, clock=_Clock(),
                    min_first=1)
    st2.feed("hello world")
    st2.feed("hello again")
    assert st2.message_id is None


# -- Gateway plumbing ---------------------------------------------------------

def _gateway(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config
    cfg = {**config.DEFAULT_CONFIG, "provider": "claude-cli",
           "gateway_persistent": True, "gateway_prewarm": False}
    config.save_config(cfg)
    from birkin.gateway.core import Gateway
    return Gateway(config.load_config())


class _FakeAskSession:
    def __init__(self):
        self.seen_on_text = "unset"

    def ask(self, text, on_text=None):
        self.seen_on_text = on_text
        if on_text:
            on_text("partial ")
        return "partial done"

    def close(self):
        pass

    def is_alive(self):
        return True


def test_handle_passes_on_text_to_persistent_session(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    fake = _FakeAskSession()
    gw._claude_sessions.put(("telegram", "c1"), fake)
    pieces: list[str] = []
    out = gw.handle("telegram", "c1", "hello", on_text=pieces.append)
    assert out == "partial done"
    assert callable(fake.seen_on_text)   # plumbing reached the session…
    assert pieces == ["partial "]        # …and the callback actually fired


def test_spare_session_adopted_once(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    fake = _FakeAskSession()
    gw._spare = fake
    assert gw._new_claude_session(("http", "x")) is fake
    assert gw._spare is None          # adopted exactly once


class _ClosableFake(_FakeAskSession):
    def __init__(self):
        super().__init__()
        self.closed = False

    def close(self):
        self.closed = True


def test_restart_discards_the_stale_spare(tmp_path, monkeypatch):
    # regression: the spare carries a PRE-restart persona/config snapshot
    gw = _gateway(tmp_path, monkeypatch)
    stale = _ClosableFake()
    gw._spare = stale
    with gw._lock:
        gw.restart()
    assert stale.closed is True
    assert gw._spare is not stale


def test_clean_hooks_and_thinking_knob_reach_the_child(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    s = gw._build_claude_session()
    try:
        assert s.settings == {"disableAllHooks": True}
        assert s.env_extra["MAX_THINKING_TOKENS"] == "0"
    finally:
        s.close()


# -- codex path: warm app-server sessions (CodexAppServerSession) ------------

def _codex_gateway(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config
    cfg = {**config.DEFAULT_CONFIG, "provider": "codex-cli",
           "model": "gpt-5.5", "gateway_persistent": True,
           "gateway_prewarm": False}
    config.save_config(cfg)
    from birkin.gateway.core import Gateway
    return Gateway(config.load_config())


def test_codex_gateway_is_persistent_with_appserver_session(tmp_path,
                                                            monkeypatch):
    from birkin.codex_session import CodexAppServerSession
    gw = _codex_gateway(tmp_path, monkeypatch)
    assert gw._persistent is True             # codex-cli now warms too
    s = gw._build_claude_session()            # constructor does NOT spawn
    assert isinstance(s, CodexAppServerSession)
    assert s.model == "gpt-5.5"
    assert s.preamble                         # persona/memory rides turn 1
    s.close()                                 # safe on an unspawned session


def test_streamer_finalize_fallback_when_nothing_streamed():
    st = _Streamer(lambda t: "m1", lambda m, t: True, clock=_Clock())
    assert st.message_id is None
    assert st.text() == ""


def test_edit_treats_not_modified_as_success_and_400_as_failure(monkeypatch):
    # regression: a masked genuine failure used to skip the delivery fallback
    import io
    import urllib.error
    from birkin.gateway.channels.telegram import TelegramChannel

    ch = TelegramChannel("tok")

    def raise_http(desc):
        def _call(method, params, timeout=60):
            body = json.dumps({"ok": False, "description": desc}).encode()
            raise urllib.error.HTTPError("u", 400, "Bad Request", {},
                                         io.BytesIO(body))
        return _call

    monkeypatch.setattr(ch, "_call",
                        raise_http("Bad Request: message is not modified"))
    assert ch._edit("c", "m", "same text") is True     # already displayed
    monkeypatch.setattr(ch, "_call",
                        raise_http("Bad Request: can't parse entities"))
    assert ch._edit("c", "m", "<b>bad") is False       # real failure -> fallback


# -- CodexAppServerSession protocol (no subprocess) ---------------------------

def test_codex_turn_streams_items_and_sends_preamble_once(monkeypatch):
    from birkin.codex_session import CodexAppServerSession
    s = CodexAppServerSession(preamble="PERSONA BLOCK")
    s._thread_id = "t1"
    sent: list[tuple[str, dict]] = []

    def fake_request(method, params=None, timeout=None):
        sent.append((method, params or {}))
        # queue this turn's notifications at turn/start time
        s._notes.put({"method": "item/completed",
                      "params": {"item": {"type": "agentMessage",
                                          "text": "part one"}}})
        s._notes.put({"method": "item/completed",
                      "params": {"item": {"type": "agentMessage",
                                          "text": "final answer"}}})
        s._notes.put({"method": "turn/completed",
                      "params": {"turn": {"status": "completed"}}})
        return {}
    monkeypatch.setattr(s, "request", fake_request)
    got: list[str] = []
    out = s._turn("hello", got.append, timeout=5)
    assert out == "final answer"              # last agent item is canonical
    assert got == ["part one", "\n\nfinal answer"]
    assert "PERSONA BLOCK" in sent[0][1]["input"][0]["text"]
    out2 = s._turn("again", None, timeout=5)
    assert out2 == "final answer"
    assert "PERSONA BLOCK" not in sent[1][1]["input"][0]["text"]  # once only


def test_codex_reader_declines_server_requests_and_routes_replies():
    from birkin.codex_session import CodexAppServerSession
    import json as _json
    s = CodexAppServerSession()
    declined: list[dict] = []
    s._send = declined.append                 # capture outbound frames
    import queue as _queue
    rq: "_queue.Queue[dict]" = _queue.Queue()
    s._replies[7] = rq
    lines = [
        _json.dumps({"id": 7, "result": {"ok": True}}),          # reply
        _json.dumps({"id": 99, "method": "execApproval",         # server req
                     "params": {"command": "rm -rf /"}}),
        _json.dumps({"method": "item/completed", "params": {}}), # notification
    ]
    s._read_stdout(lines, s._notes)
    assert rq.get_nowait()["result"] == {"ok": True}
    assert declined == [{"id": 99, "result": {"decision": "denied"}}]
    assert s._notes.get_nowait()["method"] == "item/completed"
    assert s._notes.get_nowait() is None      # sentinel after pipe end


def test_codex_reader_writes_to_its_own_queue_not_the_current_one():
    # restart isolation: a slow reader from a KILLED process must keep
    # writing to its (abandoned) queue, never into the fresh turn's queue
    from birkin.codex_session import CodexAppServerSession
    import json as _json
    import queue as _queue
    s = CodexAppServerSession()
    old_q: "_queue.Queue" = _queue.Queue()
    s._notes = _queue.Queue()                 # the "new process" queue
    s._read_stdout([_json.dumps({"method": "item/completed", "params": {}})],
                   old_q)                     # old reader drains into old_q
    assert old_q.get_nowait()["method"] == "item/completed"
    assert old_q.get_nowait() is None
    assert s._notes.empty()                   # new queue untouched


def test_codex_unsafe_model_name_is_rejected():
    from birkin.codex_session import CodexAppServerSession, CodexSessionError
    import pytest
    s = CodexAppServerSession(model='gpt"5\", sandbox_permissions=[]')
    with pytest.raises(CodexSessionError):
        s._build_argv()
    ok = CodexAppServerSession(model="gpt-5.3-codex-spark")
    assert 'model="gpt-5.3-codex-spark"' in " ".join(ok._build_argv())


def test_closed_stdin_surfaces_as_session_error_not_valueerror():
    # concurrent close() closes stdin before _proc is nulled; a mid-turn
    # send must raise the graceful session error, not a raw ValueError
    import io
    from birkin.codex_session import CodexAppServerSession, CodexSessionError
    import pytest

    class _P:
        def __init__(self):
            self.stdin = io.StringIO()
            self.stdin.close()

        def poll(self):
            return None
    s = CodexAppServerSession()
    s._proc = _P()
    with pytest.raises(CodexSessionError):
        s._send({"method": "x"})
    s._proc = None


def test_codex_agent_text_extraction():
    from birkin.codex_session import _agent_text
    assert _agent_text({"type": "agentMessage", "text": "hi"}) == "hi"
    assert _agent_text({"type": "agent_message", "text": "hi"}) == "hi"
    assert _agent_text({"type": "agentMessage",
                        "content": [{"text": "a"}, {"text": "b"}]}) == "ab"
    assert _agent_text({"type": "commandExecution", "text": "ls"}) == ""
