"""Mid-turn steering: change course without discarding in-flight work."""

from __future__ import annotations

import threading

from birkin import abortkey
from birkin.agent import Agent


class _Reg:
    def specs(self):
        return [{"name": "read_file", "description": "d", "input_schema": {}}]

    def execute(self, name, tool_input):
        class R:
            content = "file body"
            is_error = False
        return R()


class Recorder:
    """Calls a tool for `tool_turns` turns, then answers."""

    provider = "anthropic"

    def __init__(self, tool_turns=2, steer_after=None, agent_box=None):
        self.tool_turns = tool_turns
        self.steer_after = steer_after
        self.agent_box = agent_box
        self.requests: list[list[dict]] = []

    def complete(self, *, system, messages, tools=None, model=None,
                 on_text=None, abort=None):
        self.requests.append([{"role": m["role"],
                               "content": list(m["content"])} for m in messages])
        n = len(self.requests)
        if self.steer_after == n and self.agent_box:
            # Arrives while this very call is "streaming".
            self.agent_box[0].steer("actually, check the other file")
        if n <= self.tool_turns:
            return {"role": "assistant", "stop_reason": "tool_use", "content": [
                {"type": "tool_use", "id": f"t{n}", "name": "read_file",
                 "input": {}}]}
        return {"role": "assistant", "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "done"}]}


def _agent(client, **kw):
    return Agent(client=client, system="s", registry=_Reg(),
                 self_improve=False, **kw)


def _texts(message):
    return [b["text"] for b in message["content"] if b.get("type") == "text"]


# -- the slot --------------------------------------------------------------

def test_steer_rejects_empty_text():
    agent = _agent(Recorder())
    assert agent.steer("") is False
    assert agent.steer("   ") is False
    assert agent.steer("go left") is True


def test_multiple_steers_concatenate():
    agent = _agent(Recorder())
    agent.steer("first")
    agent.steer("second")
    assert agent._drain_steer() == "first\nsecond"
    assert agent._drain_steer() == ""


def test_steer_is_thread_safe():
    agent = _agent(Recorder())
    threads = [threading.Thread(target=agent.steer, args=(f"m{i}",))
               for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(agent._drain_steer().splitlines()) == 50


# -- delivery --------------------------------------------------------------

def test_steer_lands_on_the_tool_result_message_of_the_next_call():
    box = []
    client = Recorder(tool_turns=2, steer_after=1, agent_box=box)
    agent = _agent(client)
    box.append(agent)
    agent.run("go")

    # Request 2 carries the steer folded into the tool-result user message.
    tail = client.requests[1][-1]
    assert tail["role"] == "user"
    assert [b["type"] for b in tail["content"]] == ["tool_result", "text"]
    assert "check the other file" in tail["content"][-1]["text"]
    assert "mid-turn message from the user" in tail["content"][-1]["text"]


def test_in_flight_work_is_preserved():
    box = []
    client = Recorder(tool_turns=2, steer_after=1, agent_box=box)
    agent = _agent(client)
    box.append(agent)
    reply = agent.run("go")

    assert reply == "done"                       # turn ran to completion
    assert len(client.requests) == 3             # nothing was thrown away
    assert any(b.get("type") == "tool_result"
               for m in agent.messages for b in m["content"])


def test_steer_is_delivered_only_once():
    box = []
    client = Recorder(tool_turns=3, steer_after=1, agent_box=box)
    agent = _agent(client)
    box.append(agent)
    agent.run("go")

    hits = sum("check the other file" in b.get("text", "")
               for req in client.requests for m in req for b in m["content"])
    assert hits == 3, "delivered once, then present in later history"
    # It appears in exactly one message of the final history.
    carriers = [m for m in agent.messages
                if any("check the other file" in b.get("text", "")
                       for b in m["content"])]
    assert len(carriers) == 1


def test_steer_after_the_last_tool_batch_carries_into_the_next_turn():
    client = Recorder(tool_turns=0)
    agent = _agent(client)
    agent.run("first")
    agent.steer("and also check the logs")      # no turn running now
    agent.run("second")

    user_text = _texts(client.requests[-1][-1])[0]
    assert "second" in user_text
    assert "carried over from mid-turn" in user_text
    assert "check the logs" in user_text


def test_steer_emits_an_event():
    seen = []
    box = []
    client = Recorder(tool_turns=2, steer_after=1, agent_box=box)
    agent = _agent(client, on_event=lambda e, p: seen.append((e, p)))
    box.append(agent)
    agent.run("go")
    assert ("steer", {"text": "actually, check the other file"}) in seen


def test_roles_stay_alternating_after_a_steer():
    box = []
    client = Recorder(tool_turns=2, steer_after=1, agent_box=box)
    agent = _agent(client)
    box.append(agent)
    agent.run("go")
    roles = [m["role"] for m in agent.messages]
    assert all(a != b for a, b in zip(roles, roles[1:])), roles


# -- interrupt supersedes --------------------------------------------------

def test_abort_discards_a_pending_steer():
    class Flag:
        val = False

        def is_set(self):
            return self.val

    flag = Flag()
    client = Recorder(tool_turns=5)
    agent = _agent(client)
    agent.steer("too late")
    flag.val = True

    agent.run("go", abort=flag)
    assert agent._drain_steer() == "", "an interrupt supersedes a queued steer"


def test_reset_clears_pending_steer():
    agent = _agent(Recorder())
    agent.steer("stale")
    agent.reset()
    assert agent._drain_steer() == ""


# -- the REPL key listener -------------------------------------------------

class _Listener(abortkey._Base):
    """Drives _Base._handle directly, with no terminal involved."""

    def __init__(self, on_interrupt, on_line=None):
        self._on_interrupt = on_interrupt
        self._on_line = on_line
        self._stop = threading.Event()
        self._fired = False
        self._buf = []
        self.pending_line = ""

    def _run(self):
        pass


def _type(listener, text, enter=True):
    for ch in text:
        listener._handle(ch)
    if enter:
        listener._handle("\r")


def test_typed_line_steers_without_interrupting():
    killed, steered = [], []
    lis = _Listener(lambda: killed.append(1),
                    lambda line: (steered.append(line), True)[1])
    _type(lis, "also check the logs")

    assert steered == ["also check the logs"]
    assert killed == [], "the turn must not be interrupted"
    assert lis._fired is False, "listener stays live for further steers"
    assert lis.pending_line == ""


def test_multiple_lines_can_be_steered_in_one_turn():
    steered = []
    lis = _Listener(lambda: None, lambda line: (steered.append(line), True)[1])
    _type(lis, "first")
    _type(lis, "second")
    assert steered == ["first", "second"]


def test_escape_still_kills_the_turn():
    killed, steered = [], []
    lis = _Listener(lambda: killed.append(1),
                    lambda line: (steered.append(line), True)[1])
    lis._handle(abortkey.ESC)
    assert killed == [1] and steered == []


def test_refused_steer_falls_back_to_interrupting():
    killed = []
    lis = _Listener(lambda: killed.append(1), lambda line: False)
    _type(lis, "kill it")
    assert killed == [1]
    assert lis.pending_line == "kill it"      # carried as the next message


def test_no_on_line_keeps_the_original_behavior():
    killed = []
    lis = _Listener(lambda: killed.append(1))
    _type(lis, "old behavior")
    assert killed == [1] and lis.pending_line == "old behavior"


def test_a_raising_on_line_does_not_lose_the_input():
    killed = []

    def boom(line):
        raise RuntimeError("steer backend down")

    lis = _Listener(lambda: killed.append(1), boom)
    _type(lis, "important")
    assert killed == [1] and lis.pending_line == "important"


def test_blank_enter_is_not_a_steer():
    steered, killed = [], []
    lis = _Listener(lambda: killed.append(1),
                    lambda line: (steered.append(line), True)[1])
    lis._handle("\r")
    assert steered == [] and killed == [1]
