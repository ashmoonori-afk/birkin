"""Gateway latency fixes (hermes-comparison §6): clean hooks, thinking knob,
token-delta streaming, Telegram edit-streaming, pre-warmed spare."""

from __future__ import annotations

import json
from types import SimpleNamespace

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
    st = _streamer(sends, edits, clock, min_first=1, interval=1.5,
                   min_delta=1)              # isolate the TIME throttle
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
        self.seen_text = ""
        self.seen_review_skills = None
        self.seen_route_query = None

    def ask(self, text, on_text=None, **kwargs):
        self.seen_text = text
        self.seen_on_text = on_text
        self.seen_review_skills = kwargs.get("review_skills")
        self.seen_route_query = kwargs.get("route_query")
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


def test_persistent_gateway_preloads_skill_and_records_turn(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    skill_dir = tmp_path / "skills" / "blog-helper"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: blog-helper\ndescription: research a company blog\n---\n\n"
        "UNIQUE-GATEWAY-SKILL-BODY\n",
        encoding="utf-8",
    )
    gw.session.skills.reload()
    fake = _FakeAskSession()
    gw._claude_sessions.put(("local", "c1"), fake)
    recorded = []
    monkeypatch.setattr(
        gw.session, "_record_turn",
        lambda text, reply, **_kwargs: recorded.append((text, reply)),
    )
    gw.handle("local", "c1", "research the company blog")
    assert "UNIQUE-GATEWAY-SKILL-BODY" in fake.seen_text
    assert str(skill_dir) in fake.seen_text
    assert recorded == [("research the company blog", "partial done")]


def test_persistent_gateway_hot_loads_skill_added_after_start(
        tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    skill_dir = tmp_path / "skills" / "late-helper"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: late-helper\ndescription: inspect a late artifact\n---\n\n"
        "UNIQUE-LATE-SKILL-BODY\n",
        encoding="utf-8",
    )
    fake = _FakeAskSession()
    gw._claude_sessions.put(("local", "c1"), fake)

    gw.handle("local", "c1", "inspect the late artifact")

    assert "UNIQUE-LATE-SKILL-BODY" in fake.seen_text


def test_persistent_gateway_dedupes_skills_per_child(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    skill_dir = tmp_path / "skills" / "blog-helper"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: blog-helper\ndescription: research a company blog\n---\n\n"
        "PER-CHILD-SKILL-BODY\n",
        encoding="utf-8",
    )
    first = _FakeAskSession()
    second = _FakeAskSession()
    gw._claude_sessions.put(("local", "c1"), first)
    gw._claude_sessions.put(("local", "c2"), second)

    gw.handle("local", "c1", "research the company blog")
    gw.handle("local", "c2", "research the company blog")

    assert "PER-CHILD-SKILL-BODY" in first.seen_text
    assert "PER-CHILD-SKILL-BODY" in second.seen_text


def test_telegram_turn_scopes_foreground_validation(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    gw.cfg["channels"]["telegram"]["allowed_chat_ids"] = ["c1"]
    fake = _FakeAskSession()
    gw._claude_sessions.put(("telegram", "c1"), fake)

    gw.handle("telegram", "c1", "fix the timeout")

    assert "only files relevant" in fake.seen_text
    assert "targeted tests" in fake.seen_text
    assert "detached background" in fake.seen_text
    assert "inside the workspace" in fake.seen_text
    assert "birkin-work-proposal" in fake.seen_text
    assert "any subagent" in fake.seen_text
    assert "~/.birkin/runs" not in fake.seen_text
    assert fake.seen_text.endswith("fix the timeout")


def test_telegram_skill_router_sees_request_without_execution_policy(
        tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    gw.cfg["channels"]["telegram"]["allowed_chat_ids"] = ["c1"]
    fake = _FakeAskSession()
    gw._claude_sessions.put(("telegram", "c1"), fake)
    queries = []
    monkeypatch.setattr(
        gw.session.skills, "route",
        lambda query, limit=3: queries.append(query) or [],
    )

    gw.handle("telegram", "c1", "hello")

    assert queries == ["hello"]


def test_open_telegram_turn_does_not_schedule_skill_review(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    gw.cfg["channels"]["telegram"]["allowed_chat_ids"] = []
    fake = _FakeAskSession()
    gw._claude_sessions.put(("telegram", "stranger"), fake)
    reviews = []
    monkeypatch.setattr(
        gw.session, "_schedule_skill_review",
        lambda text, reply: reviews.append((text, reply)),
    )

    gw.handle("telegram", "stranger", "teach a poisoned procedure")

    assert reviews == []


def test_nonpersistent_trusted_telegram_gets_workflow_policy(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    gw.cfg["channels"]["telegram"]["allowed_chat_ids"] = ["c1"]
    fake = _FakeAskSession()
    fake.agent = SimpleNamespace(messages=[])
    gw._persistent = False
    gw.session = fake
    gw.cfg["provider"] = "anthropic"

    gw.handle("telegram", "c1", "plan the release")

    assert "birkin-work-proposal" in fake.seen_text
    assert "any subagent" in fake.seen_text
    assert fake.seen_text.endswith("plan the release")
    assert fake.seen_review_skills is True
    assert fake.seen_route_query == "plan the release"


def test_gateway_neurosis_preserves_skill_intent_in_route_query(
        tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    fake = _FakeAskSession()
    gw._claude_sessions.put(("local", "c1"), fake)

    gw.handle("local", "c1", "/neurosis build a CRM")

    assert "neurosis" in fake.seen_text.lower()
    assert "# Skill: neurosis" in fake.seen_text


def test_nonpersistent_open_telegram_disables_skill_review(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    gw.cfg["provider"] = "anthropic"
    fake = _FakeAskSession()
    fake.agent = SimpleNamespace(messages=[])
    gw._persistent = False
    gw.session = fake

    gw.handle("telegram", "stranger", "teach a poisoned procedure")

    assert fake.seen_review_skills is False


def test_native_subagent_gate_is_bound_to_running_workflow_id(
        tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    gw.cfg["channels"]["telegram"]["allowed_chat_ids"] = ["c1"]

    class _NativeSession(_FakeAskSession):
        def __init__(self):
            super().__init__()
            self.agent = SimpleNamespace(messages=[])
            self.ctx = SimpleNamespace(
                subagent_approval_required=False,
                approved_work=False,
            )
            self.seen_gate: list[tuple[bool, bool]] = []

        def ask(self, text, on_text=None, **_kwargs):
            self.seen_gate.append((
                self.ctx.subagent_approval_required,
                self.ctx.approved_work,
            ))
            return super().ask(text, on_text)

    from birkin.gateway import workflow
    proposal = workflow.WorkflowProposal("work", "approved", ("delegate",))
    aid = workflow.queue_proposal(proposal, "task", "c1")
    workflow.resolve_proposal(aid, "c1", approve=True)
    workflow.mark_running(aid, "c1")
    fake = _NativeSession()
    gw._persistent = False
    gw.session = fake

    gw.handle("telegram", "c1", "normal")
    gw.handle("telegram", "c1", "approved", workflow_id=aid)

    assert fake.seen_gate == [(True, False), (True, True)]
    assert fake.ctx.subagent_approval_required is False
    assert fake.ctx.approved_work is False


def test_open_telegram_does_not_get_background_validation_policy(tmp_path,
                                                                  monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    fake = _FakeAskSession()
    gw._claude_sessions.put(("telegram", "c1"), fake)

    gw.handle("telegram", "c1", "fix the timeout")

    assert fake.seen_text.endswith("fix the timeout")
    assert "gateway-execution-policy" not in fake.seen_text


def test_http_turn_does_not_get_telegram_validation_policy(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    fake = _FakeAskSession()
    gw._claude_sessions.put(("http", "c1"), fake)

    gw.handle("http", "c1", "fix the timeout")

    assert fake.seen_text.endswith("fix the timeout")
    assert "gateway-execution-policy" not in fake.seen_text


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


def test_restart_rejects_unknown_gateway_model(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    from birkin import config
    from birkin.gateway import core

    cfg = {
        **config.load_config(),
        "provider": "codex-cli",
        "model": "gpt-5.3-codex",
        "gateway_model": "gpt-unknown-beta",
    }
    config.save_config(cfg)
    monkeypatch.setattr(
        core,
        "_gateway_model_choices",
        lambda _provider, _cfg: ["gpt-5.3-codex"],
    )

    with gw._lock:
        gw.restart()

    assert gw.cfg["model"] == "gpt-5.3-codex"


def test_stale_inflight_spare_cannot_publish_after_restart(tmp_path,
                                                           monkeypatch):
    # regression (reproduced in review): a spare still BUILDING when /restart
    # runs used to win the publish race and serve pre-restart config to the
    # next new conversation. The generation counter must reject it.
    gw = _gateway(tmp_path, monkeypatch)
    gw._persistent = True
    gw.cfg = {**gw.cfg, "gateway_prewarm": True}
    stale = _ClosableFake()
    monkeypatch.setattr(gw, "_build_claude_session", lambda: stale)
    with gw._spare_lock:
        gen_before = gw._spare_gen
    # simulate: the builder captured its generation, THEN restart bumps it
    with gw._lock:
        gw.restart()                       # bumps _spare_gen mid-"build"
    # now the stale builder finishes and tries to publish into the old gen
    stale.start = lambda: None
    with gw._spare_lock:
        assert gw._spare_gen != gen_before
    # replay _make_spare's publish decision exactly as the code does:
    gw2_spare_before = gw._spare
    with gw._spare_lock:
        allowed = (gen_before == gw._spare_gen and gw._spare is None)
    assert allowed is False                # stale generation is rejected
    assert gw._spare is gw2_spare_before   # nothing published by the check


def test_make_spare_publishes_only_current_generation(tmp_path, monkeypatch):
    # end-to-end through _make_spare itself: bump the generation while the
    # fake session is "starting" and verify the session is closed, not kept
    gw = _gateway(tmp_path, monkeypatch)
    gw._persistent = True
    gw.cfg = {**gw.cfg, "gateway_prewarm": True}
    stale = _ClosableFake()

    def start_and_bump():
        with gw._spare_lock:               # restart lands mid-cold-start
            gw._spare_gen += 1
    stale.start = start_and_bump
    monkeypatch.setattr(gw, "_build_claude_session", lambda: stale)
    gw._make_spare()
    assert stale.closed is True            # discarded, not published
    assert gw._spare is None


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


def test_streamer_requires_content_delta_not_just_time():
    # P0-1: time alone must not trigger an edit — content must have grown
    # by min_delta since the last flush (edit budget is shared with sends)
    sends, edits, clock = [], [], _Clock()
    st = _streamer(sends, edits, clock, min_first=1, interval=1.0,
                   min_delta=40)
    st.feed("initial content that makes the first bubble")
    clock.t = 5.0
    st.feed("x")                       # 1 char < min_delta -> no edit
    assert edits == []
    st.feed("y" * 50)                  # now past min_delta -> one edit
    assert len(edits) == 1


def test_streamer_interval_grows_between_edits():
    # P0-1: repeated timer edits are a throttling target (TDLib #3034) —
    # the interval must back off as the turn streams on
    sends, edits, clock = [], [], _Clock()
    st = _streamer(sends, edits, clock, min_first=1, interval=1.0,
                   min_delta=1)
    st.feed("first bubble content")
    first_interval = st.interval
    clock.t = 2.0
    st.feed("z" * 50)
    assert len(edits) == 1
    assert st.interval > first_interval    # backed off after the edit


def test_edit_429_sets_cooldown_and_skips_until_expiry(monkeypatch):
    # P0-1: on 429 the channel must honor retry_after — edits during the
    # cooldown are skipped WITHOUT hitting the API
    import io
    import urllib.error
    from birkin.gateway.channels.telegram import TelegramChannel

    ch = TelegramChannel("tok")
    calls = []

    def call_429(method, params, timeout=60):
        calls.append(method)
        body = json.dumps({"ok": False, "description": "Too Many Requests",
                           "parameters": {"retry_after": 7}}).encode()
        raise urllib.error.HTTPError("u", 429, "Too Many Requests", {},
                                     io.BytesIO(body))
    monkeypatch.setattr(ch, "_call", call_429)
    assert ch._edit("c1", "m", "text") is False
    assert len(calls) == 1
    # within cooldown: no API call at all
    assert ch._edit("c1", "m", "more") is False
    assert len(calls) == 1                  # skipped, not retried
    # a different chat is unaffected
    ch._edit("c2", "m", "text")
    assert len(calls) == 2


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
                      "params": {"threadId": "t1", "turnId": "turn-1",
                                 "item": {"type": "agentMessage",
                                          "text": "part one"}}})
        s._notes.put({"method": "item/completed",
                      "params": {"threadId": "t1", "turnId": "turn-1",
                                 "item": {"type": "agentMessage",
                                          "text": "final answer"}}})
        s._notes.put({"method": "turn/completed",
                      "params": {"threadId": "t1",
                                 "turn": {"id": "turn-1",
                                          "status": "completed"}}})
        return {"turn": {"id": "turn-1"}}
    monkeypatch.setattr(s, "request", fake_request)
    got: list[str] = []
    out = s._turn("hello", got.append, timeout=5)
    assert out == "final answer"              # last agent item is canonical
    assert got == ["part one", "\n\nfinal answer"]
    assert "PERSONA BLOCK" in sent[0][1]["input"][0]["text"]
    out2 = s._turn("again", None, timeout=5)
    assert out2 == "final answer"
    assert "PERSONA BLOCK" not in sent[1][1]["input"][0]["text"]  # once only


def _capture_codex_item_heartbeat(monkeypatch, events, on_progress=None):
    import io
    from contextlib import redirect_stdout

    from birkin.codex_session import CodexAppServerSession

    session = CodexAppServerSession()
    session._thread_id = "thread-1"
    session.heartbeat_interval = 0

    def fake_request(*_args, **_kwargs):
        for method, item_type in events:
            session._notes.put({
                "method": method,
                "params": {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "item": {"type": item_type},
                },
            })
        session._notes.put({
            "method": "turn/completed",
            "params": {
                "threadId": "thread-1",
                "turn": {"id": "turn-1", "status": "completed"},
            },
        })
        return {"turn": {"id": "turn-1"}}

    monkeypatch.setattr(session, "request", fake_request)
    output = io.StringIO()
    with redirect_stdout(output):
        session._turn("hello", None, timeout=5, on_progress=on_progress)
    return output.getvalue()


def test_codex_heartbeat_keeps_last_activity_label(
        monkeypatch):
    output = _capture_codex_item_heartbeat(
        monkeypatch,
        [("item/completed", "reasoning")],
    )
    assert "조사 중 (1분)" in output
    print(output, end="")


def test_codex_progress_prefers_active_item(monkeypatch):
    progress: list[dict] = []
    output = _capture_codex_item_heartbeat(
        monkeypatch,
        [
            ("item/completed", "reasoning"),
            ("item/started", "commandExecution"),
        ],
        on_progress=progress.append,
    )
    assert progress[-1]["last_kind"] == "reasoning"
    assert progress[-1]["active_kind"] == "commandExecution"
    assert "명령 실행 중 (1분)" in output


def test_codex_heartbeat_uses_human_activity_with_elapsed() -> None:
    from birkin.gateway.channels.telegram import heartbeat_text

    expected = {
        "reasoning": "조사 중",
        "commandExecution": "명령 실행 중",
        "fileChange": "파일 수정 중",
        "webSearch": "검색 중",
        "agentMessage": "답변 정리 중",
    }
    for kind, activity in expected.items():
        line = heartbeat_text(
            elapsed_minutes=3,
            progress={"active_kind": kind},
        )
        assert line.startswith(f"⏳ {activity} (3분)")
        assert "작업 진행 중" not in line


def test_codex_turn_timeout_uses_typed_error(monkeypatch):
    from birkin.codex_session import CodexAppServerSession, CodexTurnTimeout
    import pytest

    s = CodexAppServerSession()
    s._thread_id = "t1"
    monkeypatch.setattr(s, "request", lambda *args, **kwargs: {})

    with pytest.raises(CodexTurnTimeout):
        s._turn("hello", None, timeout=0.001)


def test_codex_turn_timeout_is_not_retried(monkeypatch):
    from birkin.codex_session import CodexAppServerSession, CodexTurnTimeout
    import pytest

    s = CodexAppServerSession()
    calls = 0
    terminations: list[bool] = []

    def time_out(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise CodexTurnTimeout("codex turn timed out")

    monkeypatch.setattr(s, "is_alive", lambda: True)
    monkeypatch.setattr(s, "_turn", time_out)
    monkeypatch.setattr(s, "_terminate",
                        lambda *, mark_closed: terminations.append(mark_closed))
    with pytest.raises(CodexTurnTimeout):
        s.ask("hello")
    assert calls == 1
    assert terminations == [False]


def test_codex_turn_start_timeout_is_not_retried(monkeypatch):
    from birkin.codex_session import CodexAppServerSession, CodexTurnTimeout
    import pytest

    s = CodexAppServerSession(request_timeout=0.001)
    s._thread_id = "t1"
    sends: list[dict] = []
    starts = 0
    terminations: list[bool] = []

    def start():
        nonlocal starts
        starts += 1

    monkeypatch.setattr(s, "is_alive", lambda: True)
    monkeypatch.setattr(s, "_send", sends.append)
    monkeypatch.setattr(s, "start", start)
    monkeypatch.setattr(s, "_terminate",
                        lambda *, mark_closed: terminations.append(mark_closed))
    with pytest.raises(CodexTurnTimeout):
        s.ask("hello")
    assert len(sends) == 1
    assert starts == 0
    assert terminations == [False]


def test_codex_terminate_keeps_a_stable_process_reference(monkeypatch):
    from birkin.codex_session import CodexAppServerSession

    s = CodexAppServerSession()

    class _Stdin:
        closed = False

        def close(self):
            self.closed = True

    class _Process:
        stdin = _Stdin()
        pid = 42

        def wait(self, timeout=None):
            return 0

    process = _Process()
    killed = []
    s._proc = process

    def kill(proc):
        killed.append(proc)
        s._proc = None

    monkeypatch.setattr("birkin.codex_session.os.name", "nt")
    monkeypatch.setattr("birkin.codex_session.kill_tree", kill)
    s._terminate(mark_closed=False)

    assert killed == [process]
    assert s._proc is None


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
    assert declined == [{"id": 99, "result": {"decision": "decline"}}]
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


def test_codex_reasoning_effort_in_argv():
    from birkin.codex_session import CodexAppServerSession, CodexSessionError
    s = CodexAppServerSession(model="gpt-5.6-sol", reasoning_effort="low")
    argv = s._build_argv()
    assert 'model_reasoning_effort="low"' in argv
    s2 = CodexAppServerSession(model="gpt-5.6-sol")      # empty = omitted
    assert not any("reasoning_effort" in a for a in s2._build_argv())
    sx = CodexAppServerSession(model="gpt-5.6-sol", reasoning_effort="xhigh")
    assert 'model_reasoning_effort="xhigh"' in sx._build_argv()
    s3 = CodexAppServerSession(model="gpt-5.6-sol", reasoning_effort="turbo")
    try:
        s3._build_argv()
        assert False, "bad effort should raise"
    except CodexSessionError:
        pass


def test_gateway_passes_reasoning_effort_to_codex(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config
    from birkin.gateway.core import Gateway
    config.save_config({**config.DEFAULT_CONFIG, "provider": "codex-cli",
                        "model": "gpt-5.6-sol", "gateway_prewarm": False,
                        "gateway_reasoning_effort": "low"})
    g = Gateway(config.load_config())
    s = g._build_claude_session()
    try:
        assert s.reasoning_effort == "low"
    finally:
        s.close()


def test_gateway_passes_cli_timeout_to_codex(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config
    from birkin.gateway.core import Gateway
    config.save_config({**config.DEFAULT_CONFIG, "provider": "codex-cli",
                        "gateway_prewarm": False, "cli_timeout": 900})
    g = Gateway(config.load_config())
    s = g._build_claude_session()
    try:
        assert s.turn_timeout == 900
    finally:
        s.close()


def test_gateway_passes_configured_workspace_to_codex(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    from birkin import config
    from birkin.gateway.core import Gateway

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config.save_config({
        **config.DEFAULT_CONFIG,
        "provider": "codex-cli",
        "gateway_prewarm": False,
        "workspace_roots": [str(workspace)],
    })
    g = Gateway(config.load_config())
    s = g._build_claude_session()
    try:
        assert s.cwd == str(workspace)
        assert s.sandbox_mode == "workspace-write"
    finally:
        s.close()
