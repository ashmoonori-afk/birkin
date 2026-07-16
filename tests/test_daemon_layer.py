"""Daemon resource layer: SQLite ledger, session pool, model presets."""

from __future__ import annotations

import gc
import threading
import weakref

import pytest

from birkin import ledger, presets
from birkin import pools as pools_module
from birkin.pools import SessionPool


class FakeSession:
    def __init__(self, key):
        self.key = key
        self.closed = False
        self.close_count = 0

    def close(self):
        self.closed = True
        self.close_count += 1


def _borrow(pool, key):
    return getattr(pool, "borrow", pool.get)(key)


def _release(pool, key, session):
    release = getattr(pool, "release", None)
    if release is not None:
        release(key, session)


def _borrow_count(pool, session):
    entry = getattr(pool, "_borrowed", {}).get(id(session))
    if entry is None:
        return 0
    assert entry[0] is session
    return entry[1]


def _full_error():
    return getattr(pools_module, "SessionPoolFullError", RuntimeError)


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


def test_pool_defers_eviction_while_session_is_borrowed(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(pools_module.time, "monotonic", lambda: now[0])
    pool = SessionPool(FakeSession, max_sessions=1, idle_ttl=10)
    session = _borrow(pool, "a")

    now[0] = 100.0
    assert pool.sweep() == 0
    assert session.close_count == 0
    _release(pool, "a", session)
    assert pool.sweep() == 0

    now[0] = 111.0
    assert pool.sweep() == 1
    assert session.close_count == 1


@pytest.mark.parametrize("operation", ["get", "borrow"])
def test_pool_rejects_get_and_borrow_when_every_slot_is_active(operation):
    pool = SessionPool(FakeSession, max_sessions=1, idle_ttl=9999)
    active = _borrow(pool, "a")
    acquire = pool.get if operation == "get" else lambda key: _borrow(pool, key)

    with pytest.raises(_full_error()) as caught:
        acquire("b")

    assert type(caught.value) is _full_error()
    assert pool.get("a") is active
    assert active.close_count == 0 and len(pool) == 1
    _release(pool, "a", active)


def test_pool_same_key_concurrent_borrows_share_winner():
    gate = threading.Barrier(2, timeout=2)
    made, results, errors = [], [], []

    def factory(key):
        session = FakeSession(key)
        made.append(session)
        gate.wait()
        return session

    pool = SessionPool(factory, max_sessions=1, idle_ttl=9999)

    def worker():
        try:
            results.append(_borrow(pool, "a"))
        except (_full_error(), threading.BrokenBarrierError) as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(3)

    assert all(not thread.is_alive() for thread in threads)
    assert not errors and len(results) == 2 and results[0] is results[1]
    assert len(pool) == 1 and sum(s.close_count for s in made) == 1
    assert _borrow_count(pool, results[0]) == 2
    for session in results:
        _release(pool, "a", session)
    assert _borrow_count(pool, results[0]) == 0


def test_pool_capacity_holds_under_concurrent_borrows():
    gate = threading.Barrier(2, timeout=2)
    made, results, errors = [], [], []

    def factory(key):
        session = FakeSession(key)
        made.append(session)
        gate.wait()
        return session

    pool = SessionPool(factory, max_sessions=1, idle_ttl=9999)

    def worker(key):
        try:
            results.append((key, _borrow(pool, key)))
        except (_full_error(), threading.BrokenBarrierError) as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(key,)) for key in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(3)

    assert all(not thread.is_alive() for thread in threads)
    assert len(results) == 1 and len(errors) == 1
    assert type(errors[0]) is _full_error()
    assert len(pool) == 1 and sum(s.close_count for s in made) == 1
    key, winner = results[0]
    assert pool.get(key) is winner and winner.close_count == 0
    _release(pool, key, winner)


def test_pool_stale_release_does_not_touch_replacement():
    pool = SessionPool(FakeSession, max_sessions=1, idle_ttl=9999)
    old = _borrow(pool, "a")
    replacement = FakeSession("replacement")
    pool.put("a", replacement)
    assert _borrow(pool, "a") is replacement
    assert _borrow_count(pool, old) == _borrow_count(pool, replacement) == 1

    _release(pool, "a", old)
    _release(pool, "a", old)

    assert pool.get("a") is replacement
    assert _borrow_count(pool, replacement) == 1
    _release(pool, "a", replacement)


def test_pool_final_release_drops_strong_reference():
    pool = SessionPool(FakeSession, max_sessions=1, idle_ttl=9999)
    session = _borrow(pool, "a")
    reference = weakref.ref(session)
    popped = pool.pop("a")
    assert popped is session and _borrow_count(pool, session) == 1

    _release(pool, "a", session)
    del popped, session
    gc.collect()

    assert reference() is None


def test_pool_put_preserves_strict_capacity():
    idle_pool = SessionPool(FakeSession, max_sessions=1, idle_ttl=9999)
    evicted = idle_pool.get("a")
    installed = FakeSession("b")
    idle_pool.put("b", installed)
    assert idle_pool.get("b") is installed
    assert evicted.close_count == 1 and installed.close_count == 0

    active_pool = SessionPool(FakeSession, max_sessions=1, idle_ttl=9999)
    active = _borrow(active_pool, "a")
    rejected = FakeSession("b")
    with pytest.raises(_full_error()) as caught:
        active_pool.put("b", rejected)
    assert type(caught.value) is _full_error()
    assert active_pool.get("a") is active and len(active_pool) == 1
    assert active.close_count == rejected.close_count == 0
    _release(active_pool, "a", active)


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
