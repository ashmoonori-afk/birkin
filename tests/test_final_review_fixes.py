"""Regression tests for the final-review fixes (roadmap P0-P2 hardening)."""

from __future__ import annotations

# #1 — approve() must resolve a raising action instead of wedging it -----------

def test_approve_resolves_on_executor_error(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import approvals, store
    rec = store.add_pending(category="shell", title="bad",
                            description="", payload={"command": "echo hi",
                                                     "timeout": "60s"},
                            origin="test")
    # non-numeric timeout used to raise ValueError before resolve_pending
    monkeypatch.setattr(approvals.subprocess, "run",
                        lambda *a, **k: type("P", (), {"stdout": "ok",
                                                       "stderr": "",
                                                       "returncode": 0})())
    out = approvals.approve(rec["id"])
    assert out["ok"] is True                       # bad timeout coerced, ran
    assert store.list_pending() == []              # resolved, not wedged


def test_approve_error_state_when_action_truly_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import approvals, store
    rec = store.add_pending(category="skill", title="x", description="",
                            payload={}, origin="test")
    monkeypatch.setattr(approvals, "execute_action",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    out = approvals.approve(rec["id"])
    assert out["ok"] is False and "boom" in out["error"]
    assert store.list_pending() == []              # resolved to error, not stuck


# #extra — approve/reject are locked check-execute-resolve (no double-run) ----

def test_approve_twice_runs_action_once(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import approvals, store
    rec = store.add_pending(category="skill", title="once", description="",
                            payload={}, origin="test")
    runs = {"n": 0}
    monkeypatch.setattr(approvals, "execute_action",
                        lambda *a, **k: runs.__setitem__("n", runs["n"] + 1)
                        or "done")
    a = approvals.approve(rec["id"])
    b = approvals.approve(rec["id"])            # second tap
    assert a["ok"] is True and b["ok"] is False  # already resolved
    assert runs["n"] == 1                        # executed exactly once


def test_reject_then_approve_is_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import approvals, store
    rec = store.add_pending(category="skill", title="x", description="",
                            payload={}, origin="test")
    ran = {"n": 0}
    monkeypatch.setattr(approvals, "execute_action",
                        lambda *a, **k: ran.__setitem__("n", ran["n"] + 1))
    assert approvals.reject(rec["id"])["ok"] is True
    assert approvals.approve(rec["id"])["ok"] is False   # can't approve rejected
    assert ran["n"] == 0                                 # never executed


# #4 — /remind rejects out-of-range times ------------------------------------

def test_remind_rejects_bad_time(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config
    config.save_config({**config.DEFAULT_CONFIG, "provider": "claude-cli",
                        "gateway_prewarm": False,
                        "channels": {"telegram": {"allowed_chat_ids": ["42"]}}})
    from birkin.gateway.core import Gateway
    from birkin import cron
    gw = Gateway(config.load_config())
    out = gw.handle("telegram", "42", "/remind 25:99 x")
    assert "올바르지" in out
    assert cron.load_jobs() == []                  # not created, not clamped


# #5 — warm session invalidated by /new and /model --------------------------

def test_new_conversation_drops_warm_session(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config
    config.save_config({**config.DEFAULT_CONFIG, "provider": "claude-cli",
                        "model": "haiku", "repl_warm_session": True})
    from birkin.runtime import build_session
    s = build_session(config.load_config())

    class _W:
        def __init__(self):
            self.closed = False

        def ask(self, t, on_text=None):
            return "r"

        def close(self):
            self.closed = True
    w = _W()
    s._warm = w
    s.new_conversation()
    assert w.closed is True and s._warm is None     # child context cleared
    w2 = _W()
    s._warm = w2
    s.reload_client()                               # /model
    assert w2.closed is True and s._warm is None     # respawns with new model


# #7 — tool_call deltas without 'index' don't merge into one -----------------

def test_openai_tool_calls_without_index_stay_distinct():
    from birkin.llm import LLMClient
    import json
    frames = [
        f"data: {json.dumps(o)}".encode() for o in [
            {"choices": [{"delta": {"tool_calls": [
                {"id": "a", "function": {"name": "f1", "arguments": "{}"}}]}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"id": "b", "function": {"name": "f2", "arguments": "{}"}}]}}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
        ]] + [b"data: [DONE]"]
    out = LLMClient._read_openai_stream(frames, lambda p: None)
    names = sorted(b["name"] for b in out["content"] if b["type"] == "tool_use")
    assert names == ["f1", "f2"]                    # not merged into slot 0


# #8 — memory count is exact even if a snippet mentions "- [[" ---------------

def test_memory_count_line_based():
    from birkin.memory import memory_activity_line
    # 2 results; the second snippet text itself mentions a "- [[" bullet
    body = "- [[a]]: normal\n- [[b]]: see also - [[c]] in text"
    assert memory_activity_line("memory_search", body) == "🧠 recalled 2 note(s)"


def test_gateway_codex_is_sandboxed(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config
    from birkin.codex_session import CodexAppServerSession
    from birkin.gateway.core import Gateway
    # even if the user set cli_access=full globally, the gateway forces workspace
    config.save_config({**config.DEFAULT_CONFIG, "provider": "codex-cli",
                        "model": "gpt-5.6-sol", "cli_access": "full",
                        "gateway_prewarm": False})
    g = Gateway(config.load_config())
    s = g._build_claude_session()
    try:
        assert isinstance(s, CodexAppServerSession)
        assert s.sandbox_mode == "workspace-write"   # NOT danger-full-access
        assert s.approval_policy == "never"
        assert s.network_access is False
    finally:
        s.close()


def test_approve_claims_before_executing(tmp_path, monkeypatch):
    # the long action runs OUTSIDE the lock; a concurrent approve mid-exec
    # sees status='approving' (claimed) and refuses -> no double-run.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import approvals, store
    rec = store.add_pending(category="skill", title="x", description="",
                            payload={}, origin="test")
    seen = {}

    def exec_action(cat, payload):
        # while we're "executing", the item must already be non-pending
        seen["status_during"] = store.get_pending(rec["id"])["status"]
        return "done"
    monkeypatch.setattr(approvals, "execute_action", exec_action)
    out = approvals.approve(rec["id"])
    assert out["ok"] is True
    assert seen["status_during"] == "executing"       # claimed before exec
    assert store.get_pending(rec["id"])["status"] == "approved"
    assert approvals.approve(rec["id"])["ok"] is False  # second tap refused


# -- group 2: concurrency + correctness --------------------------------------

def test_pool_capacity_holds_under_two_keys(tmp_path, monkeypatch):
    from birkin.pools import SessionPool
    closed = []
    made = {"n": 0}

    def factory(key):
        made["n"] += 1
        return type("S", (), {"key": key, "close": lambda self: closed.append(key)})()
    p = SessionPool(factory, max_sessions=1, idle_ttl=999)
    p.get("a")
    p.get("b")                          # different key: must evict, not exceed
    assert len(p._sessions) == 1        # cap held
    assert closed == ["a"]              # LRU evicted


def test_cron_claim_if_due_is_once(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import cron
    from datetime import datetime
    j = cron.add_job(name="x", hour=0, minute=0, action_type="prompt",
                     value="v")
    now = datetime.fromisoformat(j["next_run"])
    assert cron.claim_if_due(j["id"], now) is not None  # first claim wins
    assert cron.claim_if_due(j["id"], now) is None      # already stamped


def test_ledger_records_estimated_tokens(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import store, ledger
    store.save_run("chat", "hi", usage=store.estimate_usage("a" * 400))
    rows = ledger.recent(5)
    assert any(r.get("tokens", 0) > 0 for r in rows)   # not always 0 now


def test_snippet_includes_boundary_term(tmp_path, monkeypatch):
    from birkin.memory import _snippet
    # both terms in one window, but beta's END crosses best_start+width:
    # alpha@0, beta@238 (238+4=242 > width 240). Old text[:240] cut it to 'be'.
    text = "alpha" + ("x" * 233) + "beta"          # beta starts at 238
    s = _snippet(text, ["alpha", "beta"], width=240)
    assert "alpha" in s and "beta" in s            # full beta, not 'be'


def test_media_refused_for_open_bot(tmp_path, monkeypatch):
    from birkin.gateway.channels.telegram import TelegramChannel
    ch = TelegramChannel("tok", allowed_chat_ids=[])   # open bot
    calls = []
    monkeypatch.setattr(ch, "_download_media",
                        lambda fid: calls.append(fid) or "x")
    out = ch._compose_media_text({"photo": [{"file_id": "L", "file_size": 900}]})
    assert "허용된 채팅" in out and calls == []          # never downloaded


def test_callback_checks_tapping_user(tmp_path, monkeypatch):
    from birkin.gateway.channels.telegram import TelegramChannel
    from birkin import config
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    config.save_config({**config.DEFAULT_CONFIG, "provider": "claude-cli",
                        "gateway_prewarm": False,
                        "channels": {"telegram": {"allowed_chat_ids": ["42"]}}})
    from birkin.gateway.core import Gateway
    from birkin import store
    gw = Gateway(config.load_config())
    rec = store.add_pending(category="skill", title="x", description="",
                            payload={}, origin="t")
    ch = TelegramChannel("tok", allowed_chat_ids=["42"])
    calls = []
    monkeypatch.setattr(ch, "_call",
                        lambda m, p, timeout=60: calls.append((m, p)) or {"ok": True})
    # group chat 42 is allowlisted, but the TAPPER (user 999) is not
    ch._handle_callback(gw, {"id": "cb", "data": f"apv:{rec['id']}",
                             "from": {"id": 999},
                             "message": {"chat": {"id": 42}, "message_id": 1,
                                         "text": "x"}})
    assert store.list_pending()          # NOT approved by a non-allowlisted user
    assert [m for m, _ in calls] == ["answerCallbackQuery"]
