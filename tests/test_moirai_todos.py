"""A hard task gets an internal todo list, follow-ups, and visible progress.

The user's own words: a hard task should be decomposed into an internal todo
list, followed up step by step, with progress visible mid-run. Today a hard
task reaches codex as ONE opaque turn -- the 26-minute failure -- and moirai,
which already has phases, roles and a journal, has no notion of a step list.

Two pieces, tested separately:

* ``moirai.todos.TodoList`` -- the step ledger. Transitions, discovered
  follow-up work, a bounded item cap so a follow-up loop cannot run forever,
  and a snapshot/render pair the heartbeat can show.
* ``patterns/hard_task.py`` -- the runtime: a planner decomposes the task, a
  worker executes each item, each worker may report follow-ups that join the
  list, and every step announces itself through m.phase() -- which is the
  channel the gateway already forwards to chat heartbeats.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from birkin.moirai import todos


class TestTodoList:
    def test_items_start_pending(self) -> None:
        t = todos.TodoList(["설치", "테스트", "문서"])
        assert t.total == 3
        assert t.done_count == 0
        assert t.is_complete is False

    def test_start_then_done_advances(self) -> None:
        t = todos.TodoList(["a", "b"])
        i = t.next_pending()
        assert i == 0
        t.start(i)
        assert t.snapshot()["todo_current"] == "a"
        t.done(i, note="finished a")
        assert t.done_count == 1
        assert t.next_pending() == 1

    def test_complete_when_everything_is_done(self) -> None:
        t = todos.TodoList(["only"])
        t.start(0)
        t.done(0)
        assert t.is_complete is True
        assert t.next_pending() is None

    def test_followup_work_joins_the_list(self) -> None:
        """A worker that discovers new work appends it, not loses it."""
        t = todos.TodoList(["원래 일"])
        assert t.append("발견된 후속 작업") is True
        assert t.total == 2

    def test_the_item_cap_bounds_a_followup_loop(self) -> None:
        """Every worker adding a follow-up must not run forever."""
        t = todos.TodoList(["seed"], max_items=3)
        assert t.append("f1") is True
        assert t.append("f2") is True
        assert t.append("f3") is False       # over the cap: refused, not queued
        assert t.total == 3

    def test_snapshot_carries_what_a_heartbeat_needs(self) -> None:
        t = todos.TodoList(["하나", "둘", "셋"])
        t.start(0); t.done(0)
        t.start(1)
        snap = t.snapshot()
        assert snap["todo_total"] == 3
        assert snap["todo_done"] == 1
        assert snap["todo_current"] == "둘"

    def test_render_reads_like_progress(self) -> None:
        t = todos.TodoList(["하나", "둘"])
        t.start(0); t.done(0)
        t.start(1)
        line = t.render()
        assert "1/2" in line
        assert "둘" in line

    def test_emit_fires_on_every_transition(self) -> None:
        seen: list[dict] = []
        t = todos.TodoList(["a"], emit=seen.append)
        t.start(0)
        t.done(0)
        assert len(seen) >= 2
        assert seen[-1]["todo_done"] == 1

    def test_a_raising_emit_cannot_kill_a_transition(self) -> None:
        def boom(_snap: dict) -> None:
            raise RuntimeError("observer bug")

        t = todos.TodoList(["a"], emit=boom)
        t.start(0)
        t.done(0)                             # must not raise
        assert t.is_complete is True

    def test_invalid_indices_are_ignored_not_fatal(self) -> None:
        t = todos.TodoList(["a"])
        t.start(9)
        t.done(-1)
        assert t.done_count == 0


PATTERN = (Path(__file__).resolve().parent.parent
           / "birkin" / "moirai" / "patterns" / "hard_task.py")


def _load_pattern():
    spec = importlib.util.spec_from_file_location("hard_task_pattern", PATTERN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeM:
    """A MoiraiAPI stand-in: canned planner/worker answers, everything recorded."""

    def __init__(self, plan_items, worker_outputs):
        self.args = {"task": "어려운 배포 자동화"}
        self.phases: list[str] = []
        self.calls: list[dict] = []
        self._plan_items = list(plan_items)
        self._worker_outputs = list(worker_outputs)

    def phase(self, title):
        self.phases.append(str(title))

    def log(self, message):
        pass

    def agent(self, prompt, *, role=None, schema=None, label=None,
              phase=None, **_kw):
        self.calls.append({"role": role, "label": label, "prompt": prompt})
        if role == "planner":
            return {"items": self._plan_items}
        if self._worker_outputs:
            return self._worker_outputs.pop(0)
        return {"result": "done"}


class TestHardTaskPattern:
    def test_meta_declares_the_contract(self) -> None:
        module = _load_pattern()
        assert module.meta["name"]
        assert "planner" in module.meta["roles"]
        assert "worker" in module.meta["roles"]
        assert module.meta["phases"]

    def test_every_planned_item_is_executed_and_reported(self) -> None:
        module = _load_pattern()
        m = _FakeM(["의존성 설치", "테스트 실행"],
                   [{"result": "설치 완료"}, {"result": "2162 passed"}])
        report = module.main(m)
        workers = [c for c in m.calls if c["role"] == "worker"]
        assert len(workers) == 2
        assert "설치 완료" in report
        assert "2162 passed" in report

    def test_each_step_announces_itself_through_phase(self) -> None:
        """m.phase() is the channel the gateway forwards to chat heartbeats."""
        module = _load_pattern()
        m = _FakeM(["하나", "둘"], [{"result": "r1"}, {"result": "r2"}])
        module.main(m)
        assert any("1/2" in p for p in m.phases), m.phases
        assert any("2/2" in p for p in m.phases), m.phases

    def test_a_followup_is_discovered_and_executed(self) -> None:
        module = _load_pattern()
        m = _FakeM(["빌드"],
                   [{"result": "빌드 성공", "followups": ["문서 갱신"]},
                    {"result": "문서 갱신 완료"}])
        report = module.main(m)
        workers = [c for c in m.calls if c["role"] == "worker"]
        assert len(workers) == 2
        assert "문서 갱신 완료" in report

    def test_an_infinite_followup_chain_is_bounded(self) -> None:
        module = _load_pattern()
        endless = [{"result": f"step {i}", "followups": [f"more-{i}"]}
                   for i in range(50)]
        m = _FakeM(["seed"], endless)
        module.main(m)                        # must terminate
        workers = [c for c in m.calls if c["role"] == "worker"]
        assert len(workers) <= module.MAX_ITEMS

    def test_an_unfinished_report_names_what_was_dropped(self) -> None:
        """Bounded means honest: the report says follow-ups were cut."""
        module = _load_pattern()
        endless = [{"result": "r", "followups": ["again"]}] * 50
        m = _FakeM(["seed"], endless)
        report = module.main(m)
        assert "후속" in report or "cap" in report.lower()
