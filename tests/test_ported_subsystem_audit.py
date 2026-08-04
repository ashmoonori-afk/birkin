"""Audit pins for the subsystems birkin ported from hermes on 2026-07-23.

hermes has since been patching deletion-safety and recovery bugs in these
exact features (orphan sweeps deleting on unattended startup, an anti-thrash
compaction latch that could permanently disable compaction, cron scoping its
workdir to process-global state). None of those bug classes are reachable
here — these tests are what keeps that true.
"""

from __future__ import annotations

import types
from pathlib import Path

from birkin import checkpoints


def _agent(monkeypatch, n_messages: int):
    from birkin.agent import Agent
    client = types.SimpleNamespace(provider="anthropic")
    a = Agent.__new__(Agent)
    a.client = client
    a.model = "m"
    a.context_window = 200000
    a.messages = [{"role": "user", "content": f"m{i}"} for i in range(n_messages)]
    a._compact_floor = 0
    # Agent.__init__ is bypassed on purpose here, so every attribute
    # compact_now() reads must be set explicitly. _lineage_head is the head of
    # the pre-compaction snapshot chain (lineage.py).
    a._lineage_head = None
    a._emit = lambda *args, **kwargs: None
    return a


def test_compaction_latch_recovers_once_history_grows(monkeypatch):
    """A failed compaction must not disable compaction forever."""
    from birkin import compaction

    a = _agent(monkeypatch, 10)
    monkeypatch.setattr(compaction, "compact",
                        lambda *args, **kwargs: a.messages)   # no progress
    assert a.compact_now() is False
    assert a._compact_floor == 10

    # Same length: still latched (that is the anti-thrash part).
    assert a.compact_now() is False

    # Grown past the floor: it must try again, and succeed.
    a.messages = a.messages + [{"role": "user", "content": "more"}]
    monkeypatch.setattr(compaction, "compact",
                        lambda *args, **kwargs: [{"role": "user",
                                                  "content": "summary"}])
    assert a.compact_now() is True
    assert a._compact_floor == 0          # success clears the latch


def test_nothing_mutates_the_process_working_directory():
    """cron/scheduler share the gateway process; a global chdir would make one
    job's workdir leak into every other caller."""
    src = Path(__file__).resolve().parent.parent / "birkin"
    offenders = []
    for path in src.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "os.chdir(" in stripped or stripped.startswith("chdir("):
                offenders.append(f"{path.name}:{i}")
    assert not offenders, f"process-global chdir: {offenders}"


def test_checkpoint_pruning_never_touches_the_workspace(tmp_path,
                                                        monkeypatch):
    """Pruning bounds the snapshot history; it must not delete user files."""
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    work = tmp_path / "work"
    work.mkdir()
    mgr = checkpoints.CheckpointManager(enabled=True, keep=2)
    for i in range(5):
        (work / "f.txt").write_text(f"v{i}\n", encoding="utf-8")
        mgr.new_turn()
        if mgr.ensure_checkpoint(work, reason=f"t{i}") is None and i == 0:
            import pytest
            pytest.skip("git unavailable")
    assert (work / "f.txt").read_text(encoding="utf-8") == "v4\n"
    assert sorted(p.name for p in work.iterdir()) == ["f.txt"]
    assert len(mgr.list_checkpoints(work)) <= 2
