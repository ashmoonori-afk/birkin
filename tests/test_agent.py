from typing import Any

from birkin import compaction, lineage
from birkin.agent import Agent
from birkin.llm import LLMClient, StreamCallback


class FakeToolResult:
    def __init__(self, content: str) -> None:
        self.content: str | list[dict[str, Any]] = content
        self.is_error = False


class FakeRegistry:
    """A registry whose tools always succeed; records calls."""

    def __init__(self):
        self.calls: list[str] = []

    def specs(self) -> list[dict[str, Any]]:
        return [
            {"name": "read_file", "description": "d", "input_schema": {}},
            {"name": "create_skill", "description": "d", "input_schema": {}},
        ]

    def execute(
        self,
        name: str,
        tool_input: dict[str, Any],
    ) -> FakeToolResult:
        self.calls.append(name)
        return FakeToolResult(f"ok:{name}")


class FakeClient(LLMClient):
    def __init__(self, script: list[dict[str, str]]) -> None:
        super().__init__(
            provider="anthropic",
            model="m",
            api_key="",
            base_url="https://example.invalid",
        )
        self.script = list(script)
        self.systems: list[str] = []

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        on_text: StreamCallback = None,
        abort: Any | None = None,
    ) -> dict[str, Any]:
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


def test_external_tool_result_is_nonce_enveloped_before_model_reentry():
    client = FakeClient([{"type": "text", "text": "done"}])
    agent = Agent(client=client, system="BASE", registry=FakeRegistry())

    result = agent._run_one(
        {"type": "tool_use", "id": "external-1", "name": "web_fetch", "input": {}}
    )

    content = result["content"]
    assert isinstance(content, str)
    assert 'birkin-external nonce="' in content
    assert "ok:web_fetch" in content
    opening = content.splitlines()[0]
    nonce = opening.removeprefix(
        '<birkin-external nonce="'
    ).removesuffix('">')
    assert content.rstrip().endswith(
        f'</birkin-external nonce="{nonce}">'
    )


def test_agent_system_marks_external_tool_results_non_authoritative():
    client = FakeClient([{"type": "text", "text": "done"}])
    agent = Agent(client=client, system="BASE", registry=FakeRegistry())

    assert agent.run("inspect") == "done"

    assert "non-authoritative" in client.systems[0]
    assert "external" in client.systems[0]


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


def test_untrusted_turn_skips_pre_llm_hooks():
    class Hook:
        calls = 0

        def pre_llm(self, *_args, **_kwargs):
            self.calls += 1
            return "private hook context"

    hook = Hook()
    client = FakeClient([{"type": "text", "text": "done"}])
    agent = Agent(
        client=client,
        system="PUBLIC",
        registry=FakeRegistry(),
        hooks=hook,
    )

    assert agent.run("hello", trusted=False) == "done"
    assert hook.calls == 0
    assert "private hook context" not in client.systems[-1]


def test_untrusted_turn_does_not_consume_or_mutate_nudge_state():
    client = FakeClient([{"type": "text", "text": "done"}])
    agent = Agent(
        client=client,
        system="PUBLIC",
        registry=FakeRegistry(),
        memory_nudge_interval=1,
        skill_nudge_interval=1,
    )
    agent._pending_nudge = "PRIVATE NUDGE"
    agent._turns_since_memory = 7
    agent._iters_since_skill = 9

    assert agent.run("hello", trusted=False) == "done"

    assert "PRIVATE NUDGE" not in client.systems[-1]
    assert agent._pending_nudge == "PRIVATE NUDGE"
    assert agent._turns_since_memory == 7
    assert agent._iters_since_skill == 9


def test_untrusted_turn_does_not_consume_private_steering():
    client = FakeClient([{"type": "text", "text": "done"}])
    agent = Agent(
        client=client,
        system="PUBLIC",
        registry=FakeRegistry(),
    )
    agent.steer("PRIVATE STEERING")

    assert agent.run("hello", trusted=False) == "done"
    assert agent._drain_steer() == "PRIVATE STEERING"


def test_untrusted_turn_compaction_does_not_persist_lineage(monkeypatch):
    snapshots: list[list[dict[str, Any]]] = []
    monkeypatch.setattr(compaction, "should_compact", lambda *_args: True)
    monkeypatch.setattr(
        compaction,
        "compact",
        lambda _client, messages, **_kwargs: messages[-1:],
    )
    monkeypatch.setattr(
        lineage,
        "snapshot",
        lambda messages, **_kwargs: snapshots.append(messages) or "snapshot",
    )
    client = FakeClient([{"type": "text", "text": "done"}])
    agent = Agent(
        client=client,
        system="PUBLIC",
        registry=FakeRegistry(),
        context_window=1,
    )
    agent.messages = [
        {"role": "user", "content": [{"type": "text", "text": str(i)}]}
        for i in range(8)
    ]

    assert agent.run("hello", trusted=False) == "done"
    assert snapshots == []
