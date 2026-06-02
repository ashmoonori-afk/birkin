"""Edge-case tests for the agent loop: max-turns guard, tool errors, and
multiple tool_use blocks in a single assistant turn."""

from __future__ import annotations

from birkin.agent import Agent
from birkin.tools import ToolResult


class _Reg:
    def __init__(self, error: bool = False):
        self.calls: list[str] = []
        self.error = error

    def specs(self):
        return [{"name": "read_file", "description": "d", "input_schema": {}}]

    def execute(self, name, tool_input):
        self.calls.append(name)
        return ToolResult(f"{'err:' if self.error else 'ok:'}{name}",
                          is_error=self.error)


class _AlwaysTool:
    """Client that always asks for a tool — used to trigger the max-turns guard."""
    provider = "anthropic"
    model = "m"

    def complete(self, *, system, messages, tools, model=None, on_text=None, abort=None):
        return {"role": "assistant", "stop_reason": "tool_use", "content": [
            {"type": "tool_use", "id": "x", "name": "read_file", "input": {}}]}


class _MultiToolThenText:
    """Two tool_uses in one turn, then a final text."""
    def __init__(self):
        self.calls = 0
        self.provider = "anthropic"; self.model = "m"

    def complete(self, *, system, messages, tools, model=None, on_text=None, abort=None):
        self.calls += 1
        if self.calls == 1:
            return {"role": "assistant", "stop_reason": "tool_use", "content": [
                {"type": "tool_use", "id": "a", "name": "read_file", "input": {}},
                {"type": "tool_use", "id": "b", "name": "read_file", "input": {}},
            ]}
        return {"role": "assistant", "stop_reason": "end_turn", "content": [
            {"type": "text", "text": "done"}]}


def test_max_turns_guard_reports_and_stops():
    agent = Agent(client=_AlwaysTool(), system="s", registry=_Reg(),
                  max_turns=3, self_improve=False)
    out = agent.run("loop please")
    assert "Reached the maximum number of tool turns" in out
    assert "3" in out  # the limit is reported


def test_tool_error_is_propagated_into_messages():
    class _OneTool:
        provider = "anthropic"; model = "m"
        def __init__(self): self.n = 0
        def complete(self, *, system, messages, tools, model=None, on_text=None, abort=None):
            self.n += 1
            if self.n == 1:
                return {"role": "assistant", "stop_reason": "tool_use", "content": [
                    {"type": "tool_use", "id": "x", "name": "read_file", "input": {}}]}
            return {"role": "assistant", "stop_reason": "end_turn", "content": [
                {"type": "text", "text": "ok"}]}

    reg = _Reg(error=True)
    agent = Agent(client=_OneTool(), system="s", registry=reg,
                  max_turns=5, self_improve=False)
    out = agent.run("x")
    assert out == "ok"
    # the tool_result message has is_error=True
    tr_msg = agent.messages[2]
    block = tr_msg["content"][0]
    assert block["type"] == "tool_result" and block["is_error"] is True
    assert "err:read_file" in block["content"]


def test_multiple_tool_uses_in_one_turn_both_execute():
    reg = _Reg()
    agent = Agent(client=_MultiToolThenText(), system="s", registry=reg,
                  max_turns=5, self_improve=False)
    out = agent.run("two tools")
    assert out == "done"
    assert reg.calls == ["read_file", "read_file"]
    # both tool_results are in one user message
    user_after_tools = agent.messages[2]
    assert user_after_tools["role"] == "user"
    assert len(user_after_tools["content"]) == 2
    assert all(b["type"] == "tool_result" for b in user_after_tools["content"])
    assert agent.last_tools == ["read_file", "read_file"]
    assert agent.last_iterations == 1   # both tools came from ONE iteration


def test_agent_reset_clears_state():
    reg = _Reg()
    agent = Agent(client=_MultiToolThenText(), system="s", registry=reg,
                  max_turns=5, self_improve=True,
                  skill_nudge_interval=1, memory_nudge_interval=1)
    agent.run("x")
    agent.reset()
    assert agent.messages == []
    assert agent._iters_since_skill == 0
    assert agent._turns_since_memory == 0
    assert agent._pending_nudge == ""
