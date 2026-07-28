"""Automatic context compaction: boundaries, summary folding, overflow retry."""

from __future__ import annotations

import pytest

from birkin import compaction
from birkin.agent import Agent
from birkin.llm import LLMError


# -- helpers ---------------------------------------------------------------

def _user(text: str) -> dict:
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def _assistant(text: str) -> dict:
    return {"role": "assistant", "content": [{"type": "text", "text": text}]}


def _tool_call(tid: str, name: str = "read_file") -> dict:
    return {"role": "assistant", "content": [
        {"type": "tool_use", "id": tid, "name": name, "input": {"path": "a"}}]}


def _tool_result(tid: str, body: str = "ok") -> dict:
    return {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tid, "content": body,
         "is_error": False}]}


class FakeClient:
    """Minimal client: records calls, returns a canned summary."""

    provider = "anthropic"

    def __init__(self, summary: str = "GOAL — ship it.", fail: bool = False):
        self.summary = summary
        self.fail = fail
        self.calls: list[dict] = []

    def complete(self, *, system, messages, tools=None, model=None,
                 on_text=None, abort=None):
        self.calls.append({"system": system, "messages": messages, "tools": tools})
        if self.fail:
            raise LLMError("summarizer down", status=500, kind="server")
        return {"role": "assistant",
                "content": [{"type": "text", "text": self.summary}],
                "stop_reason": "end_turn"}


def _pairs(n: int) -> list[dict]:
    """n user/assistant text exchanges."""
    out: list[dict] = []
    for i in range(n):
        out.append(_user(f"question {i}"))
        out.append(_assistant(f"answer {i}"))
    return out


# -- estimation / gating ---------------------------------------------------

def test_estimate_counts_system_and_tools():
    msgs = [_user("x" * 400)]
    bare = compaction.estimate_tokens(msgs)
    with_extras = compaction.estimate_tokens(
        msgs, "s" * 400, [{"name": "t", "input_schema": {"x": "y" * 400}}])
    assert with_extras > bare + 150


def test_should_compact_threshold():
    assert compaction.should_compact(80_000, 100_000) is True
    assert compaction.should_compact(79_000, 100_000) is False
    assert compaction.should_compact(10, 0) is False  # unknown window: never


def test_is_overflow_prefers_structured_kind():
    assert compaction.is_overflow(LLMError("boom", status=413, kind="overflow"))
    assert not compaction.is_overflow(LLMError("boom", status=429,
                                               kind="rate_limit"))
    # Fallback sniff for errors raised outside the classifier.
    assert compaction.is_overflow(RuntimeError("prompt is too long"))


# -- the compaction itself -------------------------------------------------

def test_compact_keeps_head_and_tail_and_inserts_one_summary():
    msgs = _pairs(12)
    client = FakeClient()
    out = compaction.compact(client, msgs, tail_budget=200)

    assert out is not msgs
    assert len(out) < len(msgs)
    assert out[0] == msgs[0]                     # head preserved
    assert out[-1] == msgs[-1]                   # tail preserved
    texts = [b.get("text", "") for m in out for b in m["content"]]
    assert sum(compaction.SUMMARY_MARK in t for t in texts) == 1


def test_compact_never_mutates_the_input():
    msgs = _pairs(12)
    snapshot = [dict(m) for m in msgs]
    compaction.compact(FakeClient(), msgs, tail_budget=200)
    assert msgs == snapshot


def test_boundaries_never_split_a_tool_use_pair():
    # A tool-heavy conversation: every boundary choice is a chance to orphan.
    msgs: list[dict] = [_user("start")]
    for i in range(14):
        msgs.append(_tool_call(f"t{i}"))
        msgs.append(_tool_result(f"t{i}"))
    msgs.append(_assistant("done"))

    out = compaction.compact(FakeClient(), msgs, tail_budget=300)
    assert out is not msgs

    open_ids: set[str] = set()
    for m in out:
        uses = {b["id"] for b in m["content"] if b.get("type") == "tool_use"}
        results = {b["tool_use_id"] for b in m["content"]
                   if b.get("type") == "tool_result"}
        assert results <= open_ids, "tool_result with no matching tool_use"
        open_ids -= results
        assert not open_ids, "tool_use left unanswered by the next message"
        open_ids |= uses
    assert not open_ids, "conversation ends on an unanswered tool_use"


def test_roles_alternate_after_compaction():
    msgs = _pairs(12)
    out = compaction.compact(FakeClient(), msgs, tail_budget=200)
    roles = [m["role"] for m in out]
    assert all(a != b for a, b in zip(roles, roles[1:])), roles


def test_summarizer_failure_returns_history_untouched():
    msgs = _pairs(12)
    out = compaction.compact(FakeClient(fail=True), msgs, tail_budget=200)
    assert out is msgs


def test_empty_summary_returns_history_untouched():
    msgs = _pairs(12)
    out = compaction.compact(FakeClient(summary="   "), msgs, tail_budget=200)
    assert out is msgs


def test_short_history_is_left_alone():
    msgs = _pairs(2)
    assert compaction.compact(FakeClient(), msgs) is msgs


def test_second_compaction_folds_the_previous_summary():
    client = FakeClient()
    once = compaction.compact(client, _pairs(12), tail_budget=200)
    twice = compaction.compact(client, once + _pairs(10), tail_budget=200)

    texts = [b.get("text", "") for m in twice for b in m["content"]]
    assert sum(compaction.SUMMARY_MARK in t for t in texts) == 1, \
        "summaries must fold, not stack"
    ask = client.calls[-1]["messages"][0]["content"][0]["text"]
    assert "EARLIER SUMMARY" in ask


# -- agent-loop integration ------------------------------------------------

class _Registry:
    def specs(self):
        return []

    def execute(self, name, tool_input):  # pragma: no cover - never called
        raise AssertionError("no tools in these tests")


class OverflowThenOK:
    """Overflows until the history shrinks below `limit` messages."""

    provider = "anthropic"

    def __init__(self, limit: int = 6):
        self.limit = limit
        self.attempts = 0
        self.summaries = 0

    def complete(self, *, system, messages, tools=None, model=None,
                 on_text=None, abort=None):
        if tools is None:                      # this is the summarizer call
            self.summaries += 1
            return {"role": "assistant",
                    "content": [{"type": "text", "text": "GOAL — x"}],
                    "stop_reason": "end_turn"}
        self.attempts += 1
        if len(messages) > self.limit:
            raise LLMError("prompt is too long", status=400, kind="overflow")
        return {"role": "assistant",
                "content": [{"type": "text", "text": "recovered"}],
                "stop_reason": "end_turn"}


def _agent(client, **kw) -> Agent:
    return Agent(client=client, system="sys", registry=_Registry(), **kw)


def test_overflow_triggers_compact_then_retry():
    client = OverflowThenOK(limit=16)
    agent = _agent(client, context_window=1000)
    agent.messages = _pairs(12)
    before = len(agent.messages)

    reply = agent.run("go")
    assert reply == "recovered"
    assert client.summaries == 1
    assert client.attempts == 2          # failed once, retried once
    assert len(agent.messages) < before


def test_overflow_gives_up_after_the_retry_cap(monkeypatch):
    class AlwaysOverflow:
        provider = "anthropic"

        def __init__(self):
            self.attempts = 0

        def complete(self, *, system, messages, tools=None, model=None,
                     on_text=None, abort=None):
            self.attempts += 1
            raise LLMError("prompt is too long", status=400, kind="overflow")

    # Compaction always "succeeds" so only the retry cap can end the loop —
    # this is the no-infinite-retry guarantee, isolated from summary quality.
    monkeypatch.setattr(compaction, "compact",
                        lambda client, messages, **kw: list(messages)[1:])

    client = AlwaysOverflow()
    agent = _agent(client, context_window=1000)
    agent.messages = _pairs(30)
    with pytest.raises(LLMError):
        agent.run("go")
    assert client.attempts == 3          # initial + 2 retries, then surfaced


def test_non_overflow_errors_are_not_compacted_away():
    class RateLimited:
        provider = "anthropic"

        def __init__(self):
            self.summaries = 0

        def complete(self, *, system, messages, tools=None, model=None,
                     on_text=None, abort=None):
            if tools is None:
                self.summaries += 1
            raise LLMError("slow down", status=429, kind="rate_limit")

    client = RateLimited()
    agent = _agent(client, context_window=1000)
    agent.messages = _pairs(12)
    with pytest.raises(LLMError):
        agent.run("go")
    assert client.summaries == 0


def test_preflight_compacts_before_a_huge_request():
    client = FakeClient(summary="GOAL — compacted")
    agent = _agent(client, context_window=1000)   # tiny window forces the gate
    agent.messages = _pairs(30)
    agent.run("go")

    # First call is the summarizer (tools=None), then the real turn.
    assert client.calls[0]["tools"] is None
    assert client.calls[1]["tools"] == []
    assert any(compaction.SUMMARY_MARK in b.get("text", "")
               for m in client.calls[1]["messages"] for b in m["content"])


def test_cli_providers_opt_out_of_compaction():
    class CliClient(FakeClient):
        provider = "claude-cli"

    agent = _agent(CliClient(), context_window=100)
    assert agent.auto_compact is False


def test_failed_compaction_latches_until_history_grows():
    client = FakeClient(fail=True)
    agent = _agent(client, context_window=1000)
    agent.messages = _pairs(12)

    assert agent.compact_now("test") is False
    assert agent._compact_floor == len(agent.messages)
    assert agent.compact_now("test") is False     # latched: no second attempt
    assert len(client.calls) == 1

    agent.messages = agent.messages + _pairs(1)   # grew — allowed to retry
    agent.compact_now("test")
    assert len(client.calls) == 2


def test_compact_emits_an_event():
    seen: list[tuple[str, dict]] = []
    agent = _agent(FakeClient(), context_window=1000,
                   on_event=lambda e, p: seen.append((e, p)))
    agent.messages = _pairs(12)
    assert agent.compact_now("manual") is True
    assert seen[0][0] == "compact"
    assert seen[0][1]["before"] > seen[0][1]["after"]
