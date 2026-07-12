"""Regression tests for the final-review fixes (roadmap P0-P2 hardening)."""

from __future__ import annotations

import io


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
