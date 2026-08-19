"""Tests for the OODA stall tracker and its agent.py hooks."""

from __future__ import annotations

from typing import Any

from birkin.agent import Agent
from birkin.llm import LLMClient
from birkin.ooda import OodaTracker, args_digest


class FakeToolResult:
    def __init__(self, content: str) -> None:
        self.content: str | list[dict[str, Any]] = content
        self.is_error = False


class FakeRegistry:
    """A registry whose tools always succeed; records calls."""

    def __init__(self):
        self.calls: list[str] = []

    def specs(self) -> list[dict[str, Any]]:
        return [{"name": "read_file", "description": "d", "input_schema": {}}]

    def execute(self, name, tool_input):
        self.calls.append(name)
        return FakeToolResult(f"ok:{name}")


class FakeClient(LLMClient):
    def __init__(self, script: list[dict[str, Any]]) -> None:
        super().__init__(
            provider="anthropic",
            model="m",
            api_key="",
            base_url="https://example.invalid",
        )
        self.script = list(script)
        self.systems: list[str] = []

    def complete(self, *, system, messages, tools=None, model=None,
                 on_text=None, abort=None):
        self.systems.append(system)
        step = self.script.pop(0) if self.script else {"type": "text",
                                                       "text": "done"}
        if step["type"] == "tool":
            return {"role": "assistant", "stop_reason": "tool_use",
                    "content": [{"type": "tool_use", "id": step.get("id", "t"),
                                 "name": step["name"],
                                 "input": step.get("input", {})}]}
        if on_text:
            on_text(step["text"])
        return {"role": "assistant", "stop_reason": "end_turn",
                "content": [{"type": "text", "text": step["text"]}]}


def _tool_step(name: str, tid: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tool", "name": name, "id": tid, "input": tool_input}


# -- args digest stability --------------------------------------------------

def test_args_digest_stable_across_key_order():
    a = args_digest({"path": "x.py", "offset": 1, "limit": 2})
    b = args_digest({"limit": 2, "path": "x.py", "offset": 1})
    assert a == b
    assert len(a) == 40  # sha1 hex


def test_args_digest_differs_for_different_args():
    assert args_digest({"path": "a.py"}) != args_digest({"path": "b.py"})


def test_args_digest_handles_non_dict_and_unserializable():
    assert args_digest(None) == args_digest({})
    d = args_digest({"odd": object()})  # must not raise; stable per call
    assert isinstance(d, str) and len(d) == 40
    assert args_digest("plain") == args_digest({"_": "plain"})


# -- stall detection ---------------------------------------------------------

def test_three_identical_failures_trigger_stall():
    t = OodaTracker(repeats=3)
    for _ in range(2):
        t.record("bash", {"cmd": "make"}, ok=False)
        assert not t.stalled()
    t.record("bash", {"cmd": "make"}, ok=False)
    assert t.stalled()
    info = t.stall_info()
    assert info["tool"] == "bash" and info["failures"] == 3
    assert "bash" in t.reorient_note()


def test_different_args_do_not_stall():
    t = OodaTracker(repeats=3)
    for i in range(4):
        t.record("bash", {"cmd": f"try{i}"}, ok=False)
    assert not t.stalled()
    assert t.reorient_note() == ""


def test_success_resets_streak():
    t = OodaTracker(repeats=3)
    t.record("bash", {"cmd": "make"}, ok=False)
    t.record("bash", {"cmd": "make"}, ok=False)
    t.record("bash", {"cmd": "make"}, ok=True)
    t.record("bash", {"cmd": "make"}, ok=False)
    t.record("bash", {"cmd": "make"}, ok=False)
    assert not t.stalled()
    t.record("bash", {"cmd": "make"}, ok=False)
    assert t.stalled()


def test_disabled_tracker_never_stalls():
    t = OodaTracker(repeats=3, enabled=False)
    for _ in range(5):
        assert t.record("bash", {"cmd": "make"}, ok=False) is None
    assert not t.stalled()
    assert t.reorient_note() == ""


def test_acknowledge_makes_note_single_shot_per_episode():
    t = OodaTracker(repeats=3)
    for _ in range(3):
        t.record("bash", {"cmd": "make"}, ok=False)
    assert t.stalled()
    assert t.reorient_note()
    t.acknowledge()
    # One more identical failure is not a NEW episode yet.
    t.record("bash", {"cmd": "make"}, ok=False)
    assert not t.stalled()
    # A full new streak is.
    for _ in range(2):
        t.record("bash", {"cmd": "make"}, ok=False)
    assert t.stalled()


def test_reorient_note_is_ascii():
    t = OodaTracker(repeats=2)
    t.record("bash", {"cmd": "make"}, ok=False)
    t.record("bash", {"cmd": "make"}, ok=False)
    note = t.reorient_note()
    note.encode("ascii")


# -- agent hooks --------------------------------------------------------------

class _FailingRegistry(FakeRegistry):
    """read_file always fails; alt_read always succeeds."""

    def specs(self) -> list[dict[str, Any]]:
        return [{"name": "read_file", "description": "d", "input_schema": {}},
                {"name": "alt_read", "description": "d", "input_schema": {}}]

    def execute(self, name, tool_input):
        self.calls.append(name)
        if name == "alt_read":
            return FakeToolResult("ok:alt_read")
        res = FakeToolResult(f"err:{name}")
        res.is_error = True
        return res


def _fail_client(path: str, extra: list[dict[str, Any]]) -> FakeClient:
    script = [
        _tool_step("read_file", "t1", {"path": path}),
        _tool_step("read_file", "t2", {"path": path}),
        _tool_step("read_file", "t3", {"path": path}),
        {"type": "text", "text": "I give up"},
    ]
    return FakeClient(script + extra)


def test_agent_injects_reorient_note_once_and_emits_event():
    events: list[tuple[str, dict[str, Any]]] = []
    client = _fail_client("x.py", [{"type": "text", "text": "after"}])
    agent = Agent(client=client, system="BASE", registry=_FailingRegistry(),
                  max_turns=10, self_improve=False,
                  on_event=lambda e, p: events.append((e, p)))
    out = agent.run("read it")
    assert out == "I give up"
    stalls = [p for e, p in events if e == "ooda_stall"]
    assert len(stalls) == 1
    assert stalls[0]["tool"] == "read_file" and stalls[0]["failures"] == 3
    injected = [s for s in client.systems if "Stall detected" in s]
    assert len(injected) == 1  # single-shot within the turn

    # The episode was acknowledged, so the next turn does not re-inject even
    # though the tracker still holds the old failures.
    out2 = agent.run("again")
    assert out2 == "after"
    assert not any("Stall detected" in s for s in client.systems[4:])


def test_agent_no_injection_when_args_differ():
    events: list[str] = []
    client = FakeClient([
        _tool_step("read_file", "t1", {"path": "a.py"}),
        _tool_step("read_file", "t2", {"path": "b.py"}),
        _tool_step("read_file", "t3", {"path": "c.py"}),
        {"type": "text", "text": "done"},
    ])
    agent = Agent(client=client, system="BASE", registry=_FailingRegistry(),
                  max_turns=10, self_improve=False,
                  on_event=lambda e, p: events.append(e))
    assert agent.run("x") == "done"
    assert "ooda_stall" not in events
    assert not any("Stall detected" in s for s in client.systems)


def test_agent_ooda_disabled_by_flag():
    events: list[str] = []
    client = _fail_client("x.py", [])
    agent = Agent(client=client, system="BASE", registry=_FailingRegistry(),
                  max_turns=10, self_improve=False, ooda_enabled=False,
                  on_event=lambda e, p: events.append(e))
    agent.run("x")
    assert "ooda_stall" not in events
    assert not any("Stall detected" in s for s in client.systems)


def test_agent_survives_tracker_exception():
    client = _fail_client("x.py", [])
    agent = Agent(client=client, system="BASE", registry=_FailingRegistry(),
                  max_turns=10, self_improve=False)

    class _Boom:
        def record(self, *a, **k):
            raise RuntimeError("boom")

        def stalled(self):
            raise RuntimeError("boom")

        def stall_info(self):
            raise RuntimeError("boom")

        def reset(self):
            raise RuntimeError("boom")

    agent._ooda = _Boom()
    agent.reset()  # must not raise
    assert agent.run("x") == "I give up"


def test_reset_clears_ooda_state():
    agent = Agent(client=FakeClient([]), system="BASE", registry=FakeRegistry())
    agent._ooda.record("bash", {"cmd": "make"}, ok=False)
    agent._ooda_pending_note = "note"
    agent.reset()
    assert agent._ooda.steps == []
    assert agent._ooda_pending_note == ""
