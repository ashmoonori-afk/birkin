"""Recoverable lineage for compacted conversation history.

Compaction replaces the middle of a long conversation with one model-written
summary. Without a parent chain that replacement is destructive: the original
turns exist nowhere once the summary lands. hermes keeps a durable lineage
(hermes_state.py compression_close_and_publish); birkin gets the same
guarantee here -- every compaction snapshots the pre-compaction history and
links it to the previous snapshot.
"""

from __future__ import annotations

import json

import pytest

from birkin import lineage
from birkin.agent import Agent
from birkin.compaction import SUMMARY_MARK


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    return tmp_path


def _msgs(n: int, tag: str = "x") -> list[dict]:
    out = []
    for i in range(n):
        out.append({"role": "user",
                    "content": [{"type": "text", "text": f"q{tag}{i} " + "u" * 3000}]})
        out.append({"role": "assistant",
                    "content": [{"type": "text", "text": f"a{tag}{i} " + "v" * 3000}]})
    return out


class FakeClient:
    provider = "anthropic"

    def complete(self, **kwargs):
        return {"role": "assistant",
                "content": [{"type": "text", "text": "GOAL - ship it."}],
                "stop_reason": "end_turn"}


class _Registry:
    def specs(self):
        return []

    def execute(self, name, tool_input):  # pragma: no cover - never called
        raise AssertionError("no tools in this test")


class TestSnapshotStore:
    def test_snapshot_roundtrip(self, home) -> None:
        msgs = _msgs(2)
        sid = lineage.snapshot(msgs)
        assert sid
        assert lineage.load(sid) == msgs

    def test_snapshot_does_not_mutate_input(self, home) -> None:
        msgs = _msgs(2)
        frozen = json.loads(json.dumps(msgs))
        lineage.snapshot(msgs)
        assert msgs == frozen

    def test_root_snapshot_has_empty_chain(self, home) -> None:
        sid = lineage.snapshot(_msgs(1))
        assert lineage.chain(sid) == []

    def test_chain_orders_ancestors_oldest_first(self, home) -> None:
        s1 = lineage.snapshot(_msgs(1, "a"))
        s2 = lineage.snapshot(_msgs(1, "b"), parent=s1)
        s3 = lineage.snapshot(_msgs(1, "c"), parent=s2)
        assert lineage.chain(s2) == [s1]
        assert lineage.chain(s3) == [s1, s2]

    def test_unknown_id_loads_none_and_empty_chain(self, home) -> None:
        assert lineage.load("nope-00000000") is None
        assert lineage.chain("nope-00000000") == []


class TestAgentWiring:
    def _agent(self, events):
        return Agent(client=FakeClient(), system="s", registry=_Registry(),
                     on_event=lambda *a: events.append(a),
                     context_window=1000)

    @staticmethod
    def _compact_payloads(events):
        return [x for a in events for x in a
                if isinstance(x, dict) and "before" in x and "after" in x]

    def test_compact_now_records_recoverable_snapshot(self, home) -> None:
        events: list = []
        agent = self._agent(events)
        agent.messages = _msgs(20)
        original = json.loads(json.dumps(agent.messages))
        assert agent.compact_now("test") is True
        payload = self._compact_payloads(events)[-1]
        sid = payload.get("lineage")
        assert sid, "compact event must carry the snapshot id"
        assert lineage.load(sid) == original
        assert SUMMARY_MARK in json.dumps(agent.messages)

    def test_successive_compactions_form_a_parent_chain(self, home) -> None:
        events: list = []
        agent = self._agent(events)
        agent.messages = _msgs(20, "a")
        assert agent.compact_now("first") is True
        agent.messages = agent.messages + _msgs(20, "b")
        assert agent.compact_now("second") is True
        payloads = self._compact_payloads(events)
        s1, s2 = payloads[0]["lineage"], payloads[1]["lineage"]
        assert s1 and s2 and s1 != s2
        assert lineage.chain(s2) == [s1]
