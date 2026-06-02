from birkin.agent import Agent
from birkin.tools import ToolResult


class FakeRegistry:
    """A registry whose tools always succeed; records calls."""

    def __init__(self):
        self.calls: list[str] = []

    def specs(self):
        return [
            {"name": "read_file", "description": "d", "input_schema": {}},
            {"name": "create_skill", "description": "d", "input_schema": {}},
        ]

    def execute(self, name, tool_input):
        self.calls.append(name)
        return ToolResult(f"ok:{name}")


class FakeClient:
    provider = "anthropic"
    model = "m"

    def __init__(self, script):
        self.script = list(script)
        self.systems: list[str] = []

    def complete(self, *, system, messages, tools, model=None, on_text=None, abort=None):
        self.systems.append(system)
        step = self.script.pop(0) if self.script else {"type": "text", "text": "done"}
        if step["type"] == "tool":
            return {"role": "assistant", "stop_reason": "tool_use", "content": [
                {"type": "tool_use", "id": step.get("id", "t"),
                 "name": step["name"], "input": {}}]}
        if on_text:
            on_text(step["text"])
        return {"role": "assistant", "stop_reason": "end_turn",
                "content": [{"type": "text", "text": step["text"]}]}


def test_basic_tool_loop():
    client = FakeClient([{"type": "tool", "name": "read_file"},
                         {"type": "text", "text": "done"}])
    reg = FakeRegistry()
    agent = Agent(client=client, system="BASE", registry=reg, max_turns=5)
    out = agent.run("do it")
    assert out == "done"
    assert reg.calls == ["read_file"]
    assert [m["role"] for m in agent.messages] == ["user", "assistant", "user", "assistant"]
    assert agent.last_tools == ["read_file"]
    assert agent.last_iterations == 1


def test_skill_nudge_fires_after_complex_turn_then_injects_next_turn():
    client = FakeClient([{"type": "tool", "name": "read_file"},
                         {"type": "tool", "name": "read_file"},
                         {"type": "tool", "name": "read_file"},
                         {"type": "text", "text": "done"}])
    agent = Agent(client=client, system="BASE", registry=FakeRegistry(),
                  max_turns=10, self_improve=True,
                  skill_nudge_interval=3, memory_nudge_interval=99)
    agent.run("complex task")
    assert "create_skill" in agent._pending_nudge

    # next turn should inject the nudge into the system prompt, then clear it
    client.script = [{"type": "text", "text": "ok"}]
    agent.run("next")
    assert "create_skill" in client.systems[-1]
    assert agent._pending_nudge == ""


def test_skill_tool_use_resets_and_suppresses_nudge():
    client = FakeClient([{"type": "tool", "name": "create_skill"},
                         {"type": "text", "text": "saved"}])
    agent = Agent(client=client, system="BASE", registry=FakeRegistry(),
                  max_turns=10, skill_nudge_interval=1, memory_nudge_interval=99)
    agent.run("save a skill")
    assert agent._pending_nudge == ""
    assert agent._iters_since_skill == 0


def test_memory_nudge_fires_on_turn_interval():
    client = FakeClient([{"type": "text", "text": "hi"}])
    agent = Agent(client=client, system="BASE", registry=FakeRegistry(),
                  max_turns=5, skill_nudge_interval=99, memory_nudge_interval=1)
    agent.run("hello")
    assert "remember" in agent._pending_nudge


def test_self_improve_off_no_nudge():
    client = FakeClient([{"type": "tool", "name": "read_file"},
                         {"type": "tool", "name": "read_file"},
                         {"type": "tool", "name": "read_file"},
                         {"type": "text", "text": "done"}])
    agent = Agent(client=client, system="BASE", registry=FakeRegistry(),
                  max_turns=10, self_improve=False,
                  skill_nudge_interval=1, memory_nudge_interval=1)
    agent.run("x")
    assert agent._pending_nudge == ""
