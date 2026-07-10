"""Daemon resource layer: SQLite ledger, session pool, model presets."""

from __future__ import annotations

from birkin import ledger, presets
from birkin.pools import SessionPool


class FakeSession:
    def __init__(self, key):
        self.key = key
        self.closed = False

    def close(self):
        self.closed = True


def test_ledger_event_and_usage_roundtrip():
    ledger.event("run:chat", "hello", tokens=120)
    ledger.event("run:chat", "again", tokens=80)
    ledger.event("session:open", "('http','1')")   # no tokens
    assert ledger.usage("day") >= 200
    kinds = {e["kind"] for e in ledger.recent(10)}
    assert {"run:chat", "session:open"} <= kinds


def test_pool_reuses_and_lru_evicts():
    made = []

    def factory(key):
        s = FakeSession(key)
        made.append(s)
        return s

    pool = SessionPool(factory, max_sessions=2, idle_ttl=9999)
    a = pool.get("a")
    assert pool.get("a") is a          # warm reuse, no second spawn
    pool.get("b")
    pool.get("c")                      # over cap -> evicts LRU ("a")
    assert a.closed and len(pool) == 2


def test_pool_sweep_evicts_idle():
    pool = SessionPool(FakeSession, max_sessions=8, idle_ttl=0.0)
    s = pool.get("x")
    assert pool.sweep() == 1 and s.closed and len(pool) == 0


def test_pool_pop_returns_without_close():
    pool = SessionPool(FakeSession, max_sessions=8, idle_ttl=9999)
    s = pool.get("x")
    assert pool.pop("x") is s and not s.closed
    assert pool.pop("x") is None


def test_presets_families_and_deny():
    assert presets.family_of("claude-opus-4-8") == "opus"
    assert presets.family_of("claude-haiku-4-5-20251001") == "haiku"
    assert presets.family_of("gpt-5.3-codex-spark") == "spark"
    assert presets.family_of("gpt-5.5") == "gpt"
    assert presets.family_of("llama3") == "local"
    assert presets.family_of(None) == "sonnet"
    assert presets.deny_tools("haiku") == {"web", "subagent"}
    assert presets.deny_tools("claude-sonnet-5") == set()


def test_presets_overlay_and_cfg_override():
    assert "Engine preset" in presets.role_overlay("claude-opus-4-8")
    cfg = {"model_presets": {"sonnet": {"role": "be terse",
                                        "deny_tools": ["web"]}}}
    assert "be terse" in presets.role_overlay("claude-sonnet-5", cfg)
    assert presets.deny_tools("claude-sonnet-5", cfg) == {"web"}


def test_presets_are_strong_guidelines():
    # Every family carries a directive block: role, approach, output rules.
    for model, marker in [
        ("claude-opus-4-8", "VERIFY"),
        ("claude-sonnet-5", "everyday driver"),
        ("claude-haiku-4-5", "AT MOST one tool call"),
        ("gpt-5.3-codex-spark", "ONLY the requested artifact"),
        ("gpt-5.5", "full new block"),
        ("llama3", "no tools unless the user explicitly asks"),
    ]:
        overlay = presets.role_overlay(model)
        assert "ROLE:" in overlay and marker in overlay, model
    # fast/strict families are explicitly marked strict
    assert "STRICTLY" in presets.role_overlay("claude-haiku-4-5")
    assert "STRICTLY" in presets.role_overlay("gpt-5.3-codex-spark")


def test_registry_applies_model_preset(tmp_path):
    from birkin.tools import ToolContext, build_registry
    fast = build_registry(ToolContext(cfg={"model": "claude-haiku-4-5"},
                                      client=None, cwd=tmp_path))
    full = build_registry(ToolContext(cfg={"model": "claude-opus-4-8"},
                                      client=None, cwd=tmp_path))
    fast_names = {s["name"] for s in fast.specs()}
    full_names = {s["name"] for s in full.specs()}
    assert fast_names < full_names          # haiku got a strict subset
    assert not any("web" in n for n in fast_names)
