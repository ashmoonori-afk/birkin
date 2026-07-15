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


def test_cli_review_parses_improvement_and_queues_proposal():
    from birkin import config, store

    class _ReviewClient:
        provider = "claude-cli"

        def complete(self, **_kwargs):
            return {"role": "assistant", "content": [{
                "type": "text",
                "text": "```json\n{\"action\":\"improve\","
                        "\"target\":\"web-research\","
                        "\"addition\":\"Verify publication dates.\"}\n```",
            }], "stop_reason": "end_turn"}

    cfg = {**config.DEFAULT_CONFIG, "provider": "codex-cli", "model": "",
           "auto_approve": []}
    session = build_session(cfg)
    session.ctx.client = _ReviewClient()
    result = selfimprove.review_cli_turn(
        session.ctx,
        "USER:\nresearch a source\n\nASSISTANT:\ndone",
    )
    pending = store.list_pending()
    assert "awaiting approval" in result
    assert len(pending) == 1
    assert pending[0]["payload"] == {
        "action": "improve",
        "target": "web-research",
        "addition": "Verify publication dates.",
    }


def test_cli_review_uses_read_only_client_copy():
    from birkin import config

    class _ReviewClient:
        provider = "claude-cli"
        cli_access = "workspace"

        def complete(self, **_kwargs):
            assert self.cli_access == "read-only"
            return {"role": "assistant", "content": [{
                "type": "text", "text": '{"action":"none"}',
            }], "stop_reason": "end_turn"}

    session = build_session({**config.DEFAULT_CONFIG, "provider": "codex-cli",
                             "model": ""})
    session.ctx.client = _ReviewClient()
    assert selfimprove.review_cli_turn(session.ctx, "USER:\nx") == (
        "Nothing new worth saving.")


def test_cli_review_canonicalizes_improvement_target():
    from birkin import config, store

    class _ReviewClient:
        provider = "claude-cli"

        def complete(self, **_kwargs):
            return {"role": "assistant", "content": [{
                "type": "text",
                "text": '{"action":"improve","target":"WEB-RESEARCH",'
                        '"addition":"Verify dates."}',
            }], "stop_reason": "end_turn"}

    session = build_session({**config.DEFAULT_CONFIG, "provider": "claude-cli",
                             "model": "", "auto_approve": []})
    session.ctx.client = _ReviewClient()
    selfimprove.review_cli_turn(session.ctx, "USER:\nresearch")
    assert store.list_pending()[0]["payload"]["target"] == "web-research"


def test_cli_review_rejects_create_name_that_slugs_to_existing_skill():
    from birkin import config, store

    class _ReviewClient:
        provider = "claude-cli"

        def complete(self, **_kwargs):
            return {"role": "assistant", "content": [{
                "type": "text",
                "text": '{"action":"create","name":"web research",'
                        '"description":"duplicate","body":"replacement"}',
            }], "stop_reason": "end_turn"}

    session = build_session({**config.DEFAULT_CONFIG, "provider": "claude-cli",
                             "model": "", "auto_approve": []})
    session.ctx.client = _ReviewClient()
    result = selfimprove.review_cli_turn(session.ctx, "USER:\nresearch")
    assert result == "Nothing new worth saving."
    assert store.list_pending() == []


def test_cli_review_rejects_create_without_raw_name():
    from birkin import config, store

    class _ReviewClient:
        provider = "claude-cli"

        def complete(self, **_kwargs):
            return {"role": "assistant", "content": [{
                "type": "text",
                "text": '{"action":"create","description":"missing",'
                        '"body":"must not persist"}',
            }], "stop_reason": "end_turn"}

    session = build_session({**config.DEFAULT_CONFIG, "provider": "claude-cli",
                             "model": "", "auto_approve": []})
    session.ctx.client = _ReviewClient()
    result = selfimprove.review_cli_turn(session.ctx, "USER:\nresearch")
    assert result == "Nothing new worth saving."
    assert store.list_pending() == []


def test_cli_review_disabled_for_non_hardened_provider():
    class _Client:
        provider = "codex-cli"

        def complete(self, **_kwargs):
            raise AssertionError("review must not run")

    session = build_session({"provider": "codex-cli", "model": ""})
    session.ctx.client = _Client()
    assert selfimprove.review_cli_turn(session.ctx, "USER:\nx") == (
        "Nothing new worth saving.")


def test_cli_review_redacts_secrets_before_model_call():
    captured = {}

    class _Client:
        provider = "claude-cli"
        cli_access = "workspace"

        def complete(self, **kwargs):
            captured.update(kwargs)
            return {"role": "assistant", "content": [{
                "type": "text", "text": '{"action":"none"}',
            }], "stop_reason": "end_turn"}

    session = build_session({"provider": "claude-cli", "model": ""})
    session.ctx.client = _Client()
    selfimprove.review_cli_turn(
        session.ctx, "USER:\napi_key=top-secret\n\nASSISTANT:\ndone")
    sent = captured["messages"][0]["content"][0]["text"]
    assert "top-secret" not in sent
    assert "[redacted]" in sent


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
