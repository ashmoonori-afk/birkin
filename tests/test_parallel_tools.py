"""Read-only tool batches run concurrently; writers stay sequential."""

from __future__ import annotations

import threading
import time

from birkin import parallel
from birkin.agent import Agent


def _tu(name, tid=None, **inp):
    return {"type": "tool_use", "id": tid or f"id-{name}", "name": name,
            "input": inp}


# -- planner ---------------------------------------------------------------

def test_all_reads_form_one_parallel_run():
    calls = [_tu("read_file"), _tu("web_fetch"), _tu("memory_search")]
    assert [k for k, _ in parallel.plan_segments(calls)] == ["parallel"]


def test_a_writer_splits_the_run():
    calls = [_tu("read_file", "a"), _tu("read_file", "b"),
             _tu("write_file", "w"),
             _tu("web_fetch", "c"), _tu("web_fetch", "d")]
    kinds = [(k, [c["id"] for c in v]) for k, v in parallel.plan_segments(calls)]
    assert kinds == [("parallel", ["a", "b"]),
                     ("sequential", ["w"]),
                     ("parallel", ["c", "d"])]


def test_a_lone_read_is_demoted_and_merged():
    calls = [_tu("read_file", "r"), _tu("run_shell", "s")]
    assert [(k, len(v)) for k, v in parallel.plan_segments(calls)] \
        == [("sequential", 2)]


def test_adjacent_sequential_segments_merge():
    calls = [_tu("run_shell", "s"), _tu("read_file", "r"), _tu("write_file", "w")]
    assert [(k, [c["id"] for c in v]) for k, v in parallel.plan_segments(calls)] \
        == [("sequential", ["s", "r", "w"])]


def test_emission_order_is_never_reordered():
    calls = [_tu("read_file", "1"), _tu("write_file", "2"), _tu("read_file", "3")]
    flat = [c["id"] for _, v in parallel.plan_segments(calls) for c in v]
    assert flat == ["1", "2", "3"]


def test_non_dict_input_is_a_barrier():
    bad = {"type": "tool_use", "id": "x", "name": "read_file", "input": "oops"}
    assert parallel.is_safe(bad) is False


def test_load_skill_is_not_parallel_safe():
    # It mutates SkillManager state and writes the curator ledger.
    assert "load_skill" not in parallel.PARALLEL_SAFE_TOOLS
    assert parallel.is_safe(_tu("load_skill")) is False


def test_every_writer_is_excluded():
    for name in ("write_file", "edit_file", "run_shell", "remember",
                 "memory_write_note", "memory_link", "memory_rezone",
                 "create_skill", "improve_skill", "spawn_subagent"):
        assert name not in parallel.PARALLEL_SAFE_TOOLS, name


# -- execution -------------------------------------------------------------

class SlowRegistry:
    """Each call sleeps; a barrier proves the safe ones truly overlap."""

    def __init__(self, delay=0.25, expect_parallel=0):
        self.delay = delay
        self.order: list[str] = []
        self._lock = threading.Lock()
        self.barrier = (threading.Barrier(expect_parallel, timeout=5)
                        if expect_parallel else None)

    def specs(self):
        return []

    def execute(self, name, tool_input):
        if self.barrier is not None and name in parallel.PARALLEL_SAFE_TOOLS:
            self.barrier.wait()          # times out unless they run together
        time.sleep(self.delay)
        with self._lock:
            self.order.append(name)

        class R:
            content = f"{name} ok"
            is_error = False
        return R()


class Batch:
    """Emits one fixed tool batch, then finishes."""

    provider = "anthropic"

    def __init__(self, calls):
        self.calls = calls
        self.n = 0

    def complete(self, *, system, messages, tools=None, model=None,
                 on_text=None, abort=None):
        self.n += 1
        if self.n == 1:
            return {"role": "assistant", "stop_reason": "tool_use",
                    "content": list(self.calls)}
        return {"role": "assistant", "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "done"}]}


def _agent(client, registry, **kw):
    kw.setdefault("self_improve", False)
    return Agent(client=client, system="s", registry=registry, **kw)


def test_safe_calls_actually_run_at_the_same_time():
    calls = [_tu("web_fetch", "a"), _tu("web_fetch", "b"), _tu("web_fetch", "c")]
    reg = SlowRegistry(delay=0, expect_parallel=3)   # barrier proves overlap
    agent = _agent(Batch(calls), reg)

    agent.run("go")


def test_serial_execution_is_the_baseline():
    calls = [_tu("web_fetch", "a"), _tu("web_fetch", "b"), _tu("web_fetch", "c")]
    reg = SlowRegistry(delay=0.2)
    agent = _agent(Batch(calls), reg, parallel_tools=False)

    start = time.monotonic()
    agent.run("go")
    assert time.monotonic() - start >= 0.55


def test_results_keep_emission_order_and_pair_with_their_calls():
    calls = [_tu("read_file", "r1"), _tu("web_fetch", "w1"),
             _tu("memory_search", "m1")]
    agent = _agent(Batch(calls), SlowRegistry(delay=0.01))
    agent.run("go")

    results = [b for m in agent.messages for b in m["content"]
               if b.get("type") == "tool_result"]
    assert [b["tool_use_id"] for b in results] == ["r1", "w1", "m1"]
    assert results[0]["content"] == "read_file ok"
    external = results[1]["content"]
    assert isinstance(external, str)
    opening = external.splitlines()[0]
    nonce = opening.removeprefix(
        '<birkin-external nonce="'
    ).removesuffix('">')
    assert len(nonce) >= 16
    assert "\nweb_fetch ok\n" in external
    assert external.rstrip().endswith(
        f'</birkin-external nonce="{nonce}">'
    )
    assert results[2]["content"] == "memory_search ok"


def test_exactly_one_result_per_call_in_a_mixed_batch():
    calls = [_tu("read_file", "a"), _tu("read_file", "b"),
             _tu("write_file", "w"), _tu("web_fetch", "c")]
    agent = _agent(Batch(calls), SlowRegistry(delay=0.01))
    agent.run("go")
    ids = [b["tool_use_id"] for m in agent.messages for b in m["content"]
           if b.get("type") == "tool_result"]
    assert ids == ["a", "b", "w", "c"]


def test_writers_run_in_order_relative_to_reads():
    calls = [_tu("read_file", "a"), _tu("write_file", "w"), _tu("read_file", "b")]
    reg = SlowRegistry(delay=0.01)
    agent = _agent(Batch(calls), reg)
    agent.run("go")
    assert reg.order == ["read_file", "write_file", "read_file"]


def test_events_fire_once_per_call_from_one_thread():
    calls = [_tu("web_fetch", "a"), _tu("web_fetch", "b")]
    seen: list[tuple[str, str]] = []
    threads: set[int] = set()

    def on_event(ev, payload):
        threads.add(threading.get_ident())
        seen.append((ev, payload.get("name", "")))

    agent = _agent(Batch(calls), SlowRegistry(delay=0.05), on_event=on_event)
    agent.run("go")

    assert len(threads) == 1, "events must come from the coordinating thread"
    assert seen.count(("tool_start", "web_fetch")) == 2
    assert seen.count(("tool_end", "web_fetch")) == 2


def test_a_raising_tool_does_not_sink_the_batch():
    class Boom(SlowRegistry):
        def execute(self, name, tool_input):
            if name == "web_fetch":
                raise RuntimeError("network gone")
            return super().execute(name, tool_input)

    calls = [_tu("read_file", "a"), _tu("web_fetch", "b"), _tu("read_file", "c")]
    agent = _agent(Batch(calls), Boom(delay=0.01))
    agent.run("go")

    results = [b for m in agent.messages for b in m["content"]
               if b.get("type") == "tool_result"]
    assert [b["tool_use_id"] for b in results] == ["a", "b", "c"]
    assert results[1]["is_error"] is True


def test_abort_still_answers_every_call():
    class Flag:
        val = False

        def is_set(self):
            return self.val

    flag = Flag()

    class Slow(SlowRegistry):
        def execute(self, name, tool_input):
            flag.val = True              # abort raised while the batch runs
            return super().execute(name, tool_input)

    calls = [_tu("web_fetch", "a"), _tu("web_fetch", "b"), _tu("web_fetch", "c")]
    agent = _agent(Batch(calls), Slow(delay=0.05))
    agent.run("go", abort=flag)

    results = [b for m in agent.messages for b in m["content"]
               if b.get("type") == "tool_result"]
    assert [b["tool_use_id"] for b in results] == ["a", "b", "c"], \
        "history must stay API-valid even when aborted mid-batch"


def test_single_call_batches_take_the_simple_path():
    calls = [_tu("read_file", "only")]
    reg = SlowRegistry(delay=0.01)
    agent = _agent(Batch(calls), reg)
    agent.run("go")
    assert reg.order == ["read_file"]


def test_nudge_counters_are_updated_on_the_loop_thread():
    calls = [_tu("read_file", "a"), _tu("create_skill", "s")]
    agent = _agent(Batch(calls), SlowRegistry(delay=0.01), self_improve=True)
    agent.run("go")
    assert agent.last_tools == ["read_file", "create_skill"]
    assert agent._iters_since_skill == 0      # reset by the skill tool
