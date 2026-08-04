"""A2A v1.0: an agent card, three JSON-RPC methods, and an off switch.

Agent2Agent is JSON-RPC 2.0 over HTTP with a discovery document at
``/.well-known/agent-card.json``. birkin already serves loopback HTTP and
already hand-rolls JSON-RPC for MCP, so the protocol needs no dependency --
which is the whole reason it can exist here at all under ``dependencies = []``.

Two things this module treats as non-negotiable:

* **Off by default.** An agent-to-agent endpoint accepts work from another
  program. Nobody gets that by upgrading; ``a2a_enabled`` has to be turned on
  deliberately, and while it is off every A2A path is a plain 404 -- not a
  403, not an error mentioning A2A. An off feature should be invisible, not
  merely closed.
* **Behind the existing token.** The dashboard already requires
  ``X-Birkin-Token`` on POST. An RPC that submits a task is at least as
  consequential as approving one, so it stays behind the same gate.
"""

from __future__ import annotations

import json

import pytest

from birkin import a2a


def _card(cfg=None):
    return a2a.agent_card("http://127.0.0.1:8787", cfg or {"a2a_enabled": True})


class TestAgentCard:
    def test_it_names_the_protocol_version(self) -> None:
        assert _card()["protocolVersion"].startswith("1.")

    def test_it_carries_a_name_and_a_url(self) -> None:
        card = _card()
        assert card["name"]
        assert card["url"] == "http://127.0.0.1:8787/a2a"

    def test_it_declares_at_least_one_skill(self) -> None:
        skills = _card()["skills"]
        assert isinstance(skills, list) and skills
        assert all({"id", "name", "description"} <= set(s) for s in skills)

    def test_it_declares_its_transport_and_input_modes(self) -> None:
        card = _card()
        assert card["preferredTransport"] == "JSONRPC"
        assert "text/plain" in card["defaultInputModes"]

    def test_it_does_not_advertise_streaming_it_cannot_do(self) -> None:
        """A card claiming push notifications it never sends is a broken peer."""
        caps = _card()["capabilities"]
        assert caps["streaming"] is False
        assert caps["pushNotifications"] is False


class TestMessageSend:
    def test_a_message_returns_a_completed_task(self) -> None:
        reply = a2a.handle({"jsonrpc": "2.0", "id": 1, "method": "message/send",
                            "params": {"message": {"role": "user", "parts": [
                                {"kind": "text", "text": "ping"}]}}},
                           run=lambda text: f"echo:{text}")
        result = reply["result"]
        assert reply["jsonrpc"] == "2.0" and reply["id"] == 1
        assert result["status"]["state"] == "completed"
        assert "echo:ping" in json.dumps(result, ensure_ascii=False)

    def test_the_task_gets_an_id_that_tasks_get_can_find(self) -> None:
        sent = a2a.handle({"jsonrpc": "2.0", "id": 1, "method": "message/send",
                           "params": {"message": {"role": "user", "parts": [
                               {"kind": "text", "text": "hello"}]}}},
                          run=lambda text: "done")
        task_id = sent["result"]["id"]
        got = a2a.handle({"jsonrpc": "2.0", "id": 2, "method": "tasks/get",
                          "params": {"id": task_id}}, run=lambda text: "")
        assert got["result"]["id"] == task_id

    def test_korean_text_survives_the_round_trip(self) -> None:
        reply = a2a.handle({"jsonrpc": "2.0", "id": 1, "method": "message/send",
                            "params": {"message": {"role": "user", "parts": [
                                {"kind": "text", "text": "안녕하세요"}]}}},
                           run=lambda text: f"받았습니다: {text}")
        assert "받았습니다: 안녕하세요" in json.dumps(reply, ensure_ascii=False)

    def test_a_message_with_no_text_part_is_an_invalid_params_error(self) -> None:
        reply = a2a.handle({"jsonrpc": "2.0", "id": 1, "method": "message/send",
                            "params": {"message": {"role": "user", "parts": []}}},
                           run=lambda text: "never called")
        assert reply["error"]["code"] == -32602

    def test_a_failing_agent_becomes_a_failed_task_not_a_crash(self) -> None:
        def boom(text: str) -> str:
            raise RuntimeError("the model is down")

        reply = a2a.handle({"jsonrpc": "2.0", "id": 1, "method": "message/send",
                            "params": {"message": {"role": "user", "parts": [
                                {"kind": "text", "text": "x"}]}}}, run=boom)
        assert reply["result"]["status"]["state"] == "failed"


class TestTasksGetAndCancel:
    def test_an_unknown_task_is_a_task_not_found_error(self) -> None:
        reply = a2a.handle({"jsonrpc": "2.0", "id": 1, "method": "tasks/get",
                            "params": {"id": "no-such-task"}},
                           run=lambda text: "")
        assert reply["error"]["code"] == -32001

    def test_cancelling_a_completed_task_is_refused(self) -> None:
        """A2A says a finished task is not cancelable, and says so by code."""
        sent = a2a.handle({"jsonrpc": "2.0", "id": 1, "method": "message/send",
                           "params": {"message": {"role": "user", "parts": [
                               {"kind": "text", "text": "x"}]}}},
                          run=lambda text: "done")
        reply = a2a.handle({"jsonrpc": "2.0", "id": 2, "method": "tasks/cancel",
                            "params": {"id": sent["result"]["id"]}},
                           run=lambda text: "")
        assert reply["error"]["code"] == -32002


class TestJsonRpcEnvelope:
    def test_an_unknown_method_is_method_not_found(self) -> None:
        reply = a2a.handle({"jsonrpc": "2.0", "id": 1, "method": "telepathy/send",
                            "params": {}}, run=lambda text: "")
        assert reply["error"]["code"] == -32601

    def test_a_non_object_request_is_an_invalid_request(self) -> None:
        assert a2a.handle(["not", "an", "object"],
                          run=lambda text: "")["error"]["code"] == -32600

    def test_the_id_is_echoed_even_on_an_error(self) -> None:
        reply = a2a.handle({"jsonrpc": "2.0", "id": "abc", "method": "nope"},
                           run=lambda text: "")
        assert reply["id"] == "abc"


class TestOffByDefault:
    def test_the_default_config_has_it_off(self) -> None:
        from birkin import config
        assert config.DEFAULT_CONFIG["a2a_enabled"] is False

    def test_enabled_reads_the_flag(self) -> None:
        assert a2a.enabled({}) is False
        assert a2a.enabled({"a2a_enabled": False}) is False
        assert a2a.enabled({"a2a_enabled": True}) is True

    def test_a_truthy_string_does_not_switch_it_on(self) -> None:
        """Turning on an inbound execution surface needs a real boolean."""
        assert a2a.enabled({"a2a_enabled": "false"}) is False
        assert a2a.enabled({"a2a_enabled": "yes"}) is False
