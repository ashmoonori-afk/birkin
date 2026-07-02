"""Tests for selfimprove.transcript_from_messages and subagent.run_subagent."""

from __future__ import annotations


from birkin import selfimprove
from birkin.runtime import build_session


def test_transcript_flattens_canonical_blocks():
    msgs = [
        {"role": "user", "content": [{"type": "text", "text": "hello"}]},
        {"role": "assistant", "content": [
            {"type": "text", "text": "hi"},
            {"type": "tool_use", "id": "t1", "name": "read_file", "input": {"p": "a"}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "OK"},
        ]},
    ]
    text = selfimprove.transcript_from_messages(msgs)
    assert "[user] hello" in text
    assert "[assistant] hi" in text
    assert "read_file" in text
    assert "tool_result" in text and "OK" in text


def test_transcript_handles_string_content():
    text = selfimprove.transcript_from_messages([
        {"role": "user", "content": "plain"},
    ])
    assert "[user] plain" in text


def test_transcript_respects_limit():
    msgs = [{"role": "user", "content": "x"}] * 40
    text = selfimprove.transcript_from_messages(msgs, limit=5)
    assert text.count("\n") <= 5


def test_reflect_disabled_returns_message():
    cfg_off = {"self_improve": False}
    # cheap ctx — selfimprove.reflect only checks ctx.cfg.self_improve before any work
    class _Ctx: cfg = cfg_off
    res = selfimprove.reflect_and_learn(_Ctx(), "anything")
    assert "disabled" in res.lower()


def test_reflect_empty_transcript_short_circuits():
    class _Ctx: cfg = {"self_improve": True}
    res = selfimprove.reflect_and_learn(_Ctx(), "")
    assert "nothing" in res.lower() or "empty" in res.lower()


# ---------------- subagent.run_subagent ----------------

def test_run_subagent_routes_through_a_real_agent(monkeypatch):
    """Build a real subagent context, but make the LLM client side-effect free."""
    from birkin import subagent as subagent_mod

    # CLI provider session: no key required, no network when we stub Agent.run.
    session = build_session({"provider": "codex-cli", "model": ""})
    captured = {}

    def fake_run(self, user_text, on_text=None):
        captured["user"] = user_text
        captured["system"] = self.system
        return "subagent-final"

    monkeypatch.setattr("birkin.agent.Agent.run", fake_run)

    result = subagent_mod.run_subagent(
        "find arxiv papers on transformers",
        session.ctx, skill_names=["arxiv"], max_turns=4)
    assert result == "subagent-final"
    # the subagent system prompt names the agent as a subagent
    assert "SUBAGENT" in captured["system"]
    assert "arxiv" in captured["user"] or "transformers" in captured["user"]
