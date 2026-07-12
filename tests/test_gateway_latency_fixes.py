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


def test_clean_hooks_and_thinking_knob_reach_the_child(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    s = gw._build_claude_session()
    try:
        assert s.settings == {"disableAllHooks": True}
        assert s.env_extra["MAX_THINKING_TOKENS"] == "0"
    finally:
        s.close()


# -- codex (non-persistent) path: new plumbing must be inert -----------------

def _codex_gateway(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config
    cfg = {**config.DEFAULT_CONFIG, "provider": "codex-cli",
           "model": "gpt-5.5", "gateway_persistent": True}
    config.save_config(cfg)
    from birkin.gateway.core import Gateway
    return Gateway(config.load_config())


class _FakeAgent:
    def __init__(self):
        self.messages = []


class _FakeRuntimeSession:
    def __init__(self):
        self.agent = _FakeAgent()

    def ask(self, text):                      # note: no on_text parameter
        return "codex reply"


def test_codex_path_ignores_on_text_and_never_prewarms(tmp_path, monkeypatch):
    gw = _codex_gateway(tmp_path, monkeypatch)
    assert gw._persistent is False            # codex-cli -> non-persistent
    gw.session = _FakeRuntimeSession()
    pieces: list[str] = []
    out = gw.handle("telegram", "c1", "hello", on_text=pieces.append)
    assert out == "codex reply"               # turn succeeds
    assert pieces == []                       # on_text inert, not crashed
    gw._make_spare()                          # prewarm is a no-op off claude
    assert gw._spare is None


def test_streamer_finalize_fallback_when_nothing_streamed():
    # codex path never feeds the streamer -> finalize must fall back to the
    # plain send path (exercised via message_id is None)
    st = _Streamer(lambda t: "m1", lambda m, t: True, clock=_Clock())
    assert st.message_id is None
    assert st.text() == ""
