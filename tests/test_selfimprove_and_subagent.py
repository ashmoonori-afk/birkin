"""Tests for selfimprove.transcript_from_messages and subagent.run_subagent."""

from __future__ import annotations

import pytest

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
    class _Ctx:
        cfg = cfg_off
    res = selfimprove.reflect_and_learn(_Ctx(), "anything")
    assert "disabled" in res.lower()


def test_reflect_empty_transcript_short_circuits():
    class _Ctx:
        cfg = {"self_improve": True}
    res = selfimprove.reflect_and_learn(_Ctx(), "")
    assert "nothing" in res.lower() or "empty" in res.lower()


def test_codex_reflection_uses_read_only_birkin_mcp_client(monkeypatch):
    seen = {}

    class _Agent:
        def __init__(self, *, client, **_kwargs):
            seen["client"] = client

        def run(self, text):
            seen["text"] = text
            return "Nothing new worth saving."

    monkeypatch.setattr(selfimprove, "Agent", _Agent)
    session = build_session({"provider": "codex-cli", "model": ""})

    secret = "sk-" + "a" * 20
    selfimprove.reflect_and_learn(
        session.ctx, f"USER:\nremember this, token={secret}")

    assert seen["client"] is not session.ctx.client
    assert seen["client"].cli_access == "read-only"
    assert seen["client"].birkin_mcp is True
    assert secret not in seen["text"]
    assert "[redacted]" in seen["text"]


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

    def fake_run(self, user_text, on_text=None, abort=None):
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


def test_run_subagent_registers_heartbeats_delivers_inbox_and_finishes(monkeypatch):
    from birkin import agentruns
    from birkin import subagent as subagent_mod

    session = build_session({"provider": "codex-cli", "model": ""})
    seen = {}

    def fake_run(self, user_text, on_text=None, abort=None):
        run = agentruns.list_runs()[0]
        seen["running"] = run
        assert agentruns.append_message(run["id"], "change course")
        self.on_event("tool_end", {"name": "read_file"})
        seen["steer"] = self._drain_steer()
        return "finished work"

    monkeypatch.setattr("birkin.agent.Agent.run", fake_run)
    assert subagent_mod.run_subagent("inspect files", session.ctx) == "finished work"

    run = agentruns.list_runs()[0]
    assert seen["running"]["status"] == "running"
    assert seen["steer"] == "change course"
    assert run["status"] == "done"
    assert run["result"] == "finished work"
    assert agentruns.drain_messages(run["id"]) == []


def test_detached_subagent_returns_at_once_and_finishes_in_the_background(
        monkeypatch):
    import threading

    from birkin import agentruns
    from birkin import subagent as subagent_mod

    session = build_session({"provider": "codex-cli", "model": ""})
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    real_finish = agentruns.finish_run

    def spy_finish(run_id, status, result=""):
        record = real_finish(run_id, status, result)
        finished.set()
        return record

    def fake_run(self, user_text, on_text=None, abort=None):
        started.set()
        self.on_event("tool_start", {"name": "read_file"})
        assert release.wait(timeout=10)
        return "background work"

    monkeypatch.setattr("birkin.agent.Agent.run", fake_run)
    monkeypatch.setattr(agentruns, "finish_run", spy_finish)

    message = subagent_mod.run_subagent("long job", session.ctx, detach=True)

    assert started.wait(timeout=10)          # the caller never waited for it
    run = agentruns.list_runs()[0]
    assert run["status"] == "running"
    assert run["id"][:8] in message and "/attach" in message

    release.set()

    assert finished.wait(timeout=10)
    final = agentruns.get_run(run["id"])
    assert final["status"] == "done"
    assert final["result"] == "background work"
    assert [event["text"] for event in final["events"]] == [
        "tool_start read_file"]


def test_run_subagent_records_error_and_reraises(monkeypatch):
    from birkin import agentruns
    from birkin import subagent as subagent_mod

    session = build_session({"provider": "codex-cli", "model": ""})

    def fail(self, user_text, on_text=None, abort=None):
        raise RuntimeError("model exploded")

    monkeypatch.setattr("birkin.agent.Agent.run", fail)
    try:
        subagent_mod.run_subagent("fail task", session.ctx)
    except RuntimeError as exc:
        assert str(exc) == "model exploded"
    else:
        raise AssertionError("subagent exception swallowed")

    run = agentruns.list_runs()[0]
    assert run["status"] == "error"
    assert "model exploded" in run["result"]


def test_nested_subagent_records_parent_relationship(monkeypatch):
    from birkin import agentruns
    from birkin import subagent as subagent_mod

    session = build_session({"provider": "codex-cli", "model": ""})
    calls = {"count": 0}

    def fake_run(self, user_text, on_text=None, abort=None):
        calls["count"] += 1
        if calls["count"] == 1:
            subagent_mod.run_subagent("nested", session.ctx)
        return user_text + " done"

    monkeypatch.setattr("birkin.agent.Agent.run", fake_run)
    subagent_mod.run_subagent("root", session.ctx)

    roots = agentruns.list_runs()
    assert len(roots) == 1
    assert roots[0]["task"] == "root"
    assert roots[0]["children"][0]["task"] == "nested"


def test_subagents_share_concurrent_and_total_node_budget(monkeypatch):
    import threading

    from birkin import agentruns
    from birkin import subagent as subagent_mod

    session = build_session({
        "provider": "codex-cli",
        "model": "",
        "subagent_tree_max_concurrent": 1,
        "subagent_tree_max_nodes": 1,
    })
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    real_finish = agentruns.finish_run

    def spy_finish(run_id, status, result=""):
        record = real_finish(run_id, status, result)
        finished.set()
        return record

    def fake_run(self, user_text, on_text=None, abort=None):
        started.set()
        assert release.wait(timeout=10)
        return "done"

    monkeypatch.setattr("birkin.agent.Agent.run", fake_run)
    monkeypatch.setattr(agentruns, "finish_run", spy_finish)
    subagent_mod.run_subagent("first", session.ctx, detach=True)
    assert started.wait(timeout=10)

    with pytest.raises(RuntimeError, match="concurrent child limit"):
        subagent_mod.run_subagent("second", session.ctx)

    release.set()
    assert finished.wait(timeout=10)

    node_session = build_session({
        "provider": "codex-cli",
        "model": "",
        "subagent_tree_max_nodes": 1,
    })
    monkeypatch.setattr(
        "birkin.agent.Agent.run",
        lambda self, user_text, on_text=None, abort=None: "done",
    )
    assert subagent_mod.run_subagent("first node", node_session.ctx) == "done"
    with pytest.raises(RuntimeError, match="total node limit"):
        subagent_mod.run_subagent("second node", node_session.ctx)


def test_subagent_tree_budget_reserves_tokens_usd_and_deadline(monkeypatch):
    from birkin import subagent as subagent_mod

    session = build_session({
        "provider": "codex-cli",
        "model": "",
        "subagent_tree_max_tokens": 100,
        "subagent_tree_max_usd": 1.0,
        "subagent_tree_deadline_seconds": 60,
    })
    monkeypatch.setattr(
        "birkin.agent.Agent.run",
        lambda self, user_text, on_text=None, abort=None: "done",
    )

    assert subagent_mod.run_subagent(
        "within budget",
        session.ctx,
        reserve_tokens=60,
        reserve_usd=0.5,
    ) == "done"

    with pytest.raises(RuntimeError, match="token budget"):
        subagent_mod.run_subagent(
            "too many tokens",
            session.ctx,
            reserve_tokens=99,
            reserve_usd=0.1,
        )
    with pytest.raises(RuntimeError, match="USD budget"):
        subagent_mod.run_subagent(
            "too much money",
            session.ctx,
            reserve_tokens=10,
            reserve_usd=0.75,
        )

    session.ctx.tree_budget.deadline = 0.0
    with pytest.raises(RuntimeError, match="deadline"):
        subagent_mod.run_subagent(
            "too late",
            session.ctx,
            reserve_tokens=10,
            reserve_usd=0.1,
        )


def test_subagent_tree_budget_rejects_zero_reservations_when_capped():
    session = build_session({
        "provider": "codex-cli",
        "model": "",
        "subagent_tree_max_tokens": 100,
        "subagent_tree_max_usd": 1.0,
    })

    with pytest.raises(RuntimeError, match="token reservation required"):
        session.ctx.tree_budget.reserve(usd=0.5)
    with pytest.raises(RuntimeError, match="USD reservation required"):
        session.ctx.tree_budget.reserve(tokens=50)


def test_subagent_deadline_aborts_execution_and_settles_lease(monkeypatch):
    from birkin import subagent as subagent_mod

    session = build_session({
        "provider": "codex-cli",
        "model": "",
        "subagent_tree_deadline_seconds": 60,
    })

    def expire(self, user_text, on_text=None, abort=None):
        assert abort is not None
        session.ctx.tree_budget.deadline = 0.0
        return "late"

    monkeypatch.setattr("birkin.agent.Agent.run", expire)

    with pytest.raises(RuntimeError, match="deadline"):
        subagent_mod.run_subagent("expires", session.ctx)
    assert session.ctx.tree_budget.active == 0


def test_subagent_setup_failure_releases_tree_lease(monkeypatch):
    from birkin import subagent as subagent_mod

    session = build_session({
        "provider": "codex-cli",
        "model": "",
        "subagent_tree_max_concurrent": 1,
    })
    monkeypatch.setattr(
        subagent_mod,
        "build_registry",
        lambda _ctx: (_ for _ in ()).throw(RuntimeError("registry failed")),
    )

    with pytest.raises(RuntimeError, match="registry failed"):
        subagent_mod.run_subagent("cannot start", session.ctx)
    assert session.ctx.tree_budget.active == 0
