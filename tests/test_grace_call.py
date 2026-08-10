"""When max_turns trips, the model gets one last no-tools turn to report."""

from __future__ import annotations

from birkin.agent import Agent
from birkin.llm import LLMError


class _Reg:
    def specs(self):
        return [{"name": "read_file", "description": "d", "input_schema": {}}]

    def execute(self, name, tool_input):
        class R:
            content = "file body"
            is_error = False
        return R()


class LoopsForever:
    """Calls a tool every turn; answers plainly once tools are withheld."""

    provider = "anthropic"

    def __init__(self, summary="I read three files; the migration is unfinished."):
        self.summary = summary
        self.calls: list[dict] = []

    def complete(self, *, system, messages, tools=None, model=None,
                 on_text=None, abort=None):
        self.calls.append({"tools": tools, "messages": list(messages)})
        if tools:
            return {"role": "assistant", "stop_reason": "tool_use", "content": [
                {"type": "tool_use", "id": f"t{len(self.calls)}",
                 "name": "read_file", "input": {}}]}
        return {"role": "assistant", "stop_reason": "end_turn",
                "content": [{"type": "text", "text": self.summary}]}


def _agent(client, **kw):
    return Agent(client=client, system="s", registry=_Reg(), max_turns=3,
                 self_improve=False, **kw)


def test_exhausted_run_returns_a_summary_plus_the_notice():
    client = LoopsForever()
    out = _agent(client).run("go")
    assert "migration is unfinished" in out
    assert "Reached the maximum number of tool turns" in out
    assert "3" in out


def test_grace_call_is_made_without_tools():
    client = LoopsForever()
    _agent(client).run("go")
    assert [c["tools"] for c in client.calls][-1] is None
    assert all(c["tools"] for c in client.calls[:-1])
    assert len(client.calls) == 4          # 3 tool turns + 1 grace call


def test_grace_prompt_folds_into_the_trailing_tool_result_message():
    client = LoopsForever()
    _agent(client).run("go")
    last_request = client.calls[-1]["messages"]
    tail = last_request[-1]
    assert tail["role"] == "user"
    types = [b["type"] for b in tail["content"]]
    assert types == ["tool_result", "text"]
    assert "maximum number of tool-calling turns" in tail["content"][-1]["text"]


def test_history_stays_valid_for_the_next_turn():
    client = LoopsForever()
    agent = _agent(client)
    agent.run("go")
    assert agent.messages[-1]["role"] == "assistant"
    # No unanswered tool_use anywhere.
    open_ids: set[str] = set()
    for m in agent.messages:
        results = {b["tool_use_id"] for b in m["content"]
                   if b.get("type") == "tool_result"}
        assert results <= open_ids
        open_ids -= results
        assert not open_ids
        open_ids |= {b["id"] for b in m["content"] if b.get("type") == "tool_use"}
    assert not open_ids


def test_a_failed_grace_call_leaves_history_untouched():
    class GraceFails(LoopsForever):
        def complete(self, *, system, messages, tools=None, model=None,
                     on_text=None, abort=None):
            if tools is None:
                raise LLMError("summarizer down", status=500, kind="server")
            return super().complete(system=system, messages=messages,
                                    tools=tools, model=model)

    agent = _agent(GraceFails())
    before_len = None
    out = agent.run("go")
    before_len = len(agent.messages)
    assert "Reached the maximum number of tool turns" in out
    # History must not end on the orphan grace prompt.
    tail = agent.messages[-1]
    assert tail["role"] == "user"
    assert all(b["type"] == "tool_result" for b in tail["content"]), \
        "the grace prompt should have been rolled back"
    assert before_len == len(agent.messages)


def test_stray_tool_use_in_the_grace_reply_is_answered():
    class DisobedientGrace(LoopsForever):
        def complete(self, *, system, messages, tools=None, model=None,
                     on_text=None, abort=None):
            if tools is None:
                return {"role": "assistant", "stop_reason": "tool_use",
                        "content": [
                            {"type": "text", "text": "one more thing"},
                            {"type": "tool_use", "id": "stray",
                             "name": "read_file", "input": {}}]}
            return super().complete(system=system, messages=messages,
                                    tools=tools, model=model)

    agent = _agent(DisobedientGrace())
    out = agent.run("go")
    assert "one more thing" in out
    tail = agent.messages[-1]
    assert tail["content"][0]["tool_use_id"] == "stray"
    assert tail["content"][0]["is_error"] is True


def test_abort_skips_the_grace_call():
    class Flag:
        def is_set(self):
            return False

    flag = Flag()

    class StopsAfterTwo(LoopsForever):
        def complete(self, *, system, messages, tools=None, model=None,
                     on_text=None, abort=None):
            res = super().complete(system=system, messages=messages,
                                   tools=tools, model=model)
            if len(self.calls) >= 2:
                flag.is_set = lambda: True
            return res

    c = StopsAfterTwo()
    agent = _agent(c)
    agent.run("go", abort=flag)
    assert all(call["tools"] for call in c.calls), "no grace call after abort"
