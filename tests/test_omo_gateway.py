from __future__ import annotations

import json
import sys
from pathlib import Path

from birkin.gateway import core
from birkin.omo import OmoController, parse_omo_command
from birkin.omo_rpc import OmoRpcClient, OmoState, command_for_session


class FakeRpc:
    def __init__(self) -> None:
        self.selected: Path | None = None
        self.prompts: list[str] = []
        self.steers: list[str] = []
        self.aborted = False
        self.closed = False

    def switch_session(self, path: Path) -> None:
        self.selected = path

    def prompt(self, message: str) -> str:
        self.prompts.append(message)
        return f"reply: {message}"

    def steer(self, message: str) -> None:
        self.steers.append(message)

    def abort(self) -> None:
        self.aborted = True

    def get_state(self) -> OmoState:
        return OmoState(session_id="abc123", is_streaming=False)

    def get_last_assistant_text(self) -> str | None:
        return "last reply"

    def close(self) -> None:
        self.closed = True


def write_session(root: Path, session_id: str, cwd: str) -> Path:
    path = root / f"{session_id}.jsonl"
    path.write_text(json.dumps({"type": "session", "id": session_id, "cwd": cwd}) + "\n", encoding="utf-8")
    return path


def test_controller_controls_selected_session_and_rejects_missing_selection(tmp_path: Path) -> None:
    first = write_session(tmp_path, "abc12345-0000", "C:/repo/one")
    rpc = FakeRpc()
    controller = OmoController(rpc=rpc, session_roots=(tmp_path,))

    assert "abc12345-0000" in controller.handle("/omo list")
    assert controller.handle("/omo use abc123") == "Selected abc12345-0000 (C:/repo/one)."
    assert rpc.selected == first
    assert controller.handle("/omo send fix the test") == "reply: fix the test"
    assert controller.handle("/omo steer check caller") == "Steering message queued."
    assert controller.handle("/omo abort") == "Abort requested."
    assert controller.handle("/omo last") == "last reply"
    assert "abc123" in controller.handle("/omo status")
    assert "No OMO session matches" in controller.handle("/omo use missing")
    empty = OmoController(rpc=rpc, session_roots=())
    assert "Select a session first" in empty.handle("/omo send hello")
    assert rpc.prompts == ["fix the test"]
    assert rpc.steers == ["check caller"]
    assert rpc.aborted


def test_gateway_registers_authorizes_and_closes_omo(monkeypatch) -> None:
    rpc = FakeRpc()
    controller = OmoController(rpc=rpc, session_roots=())
    monkeypatch.setattr(core, "OmoController", lambda: controller)
    monkeypatch.setattr(core, "build_session", lambda cfg: object())
    gateway = core.Gateway({"channels": {"telegram": {"allowed_chat_ids": ["42"]}}})

    assert "omo" in {item["command"] for item in core.command_menu()}
    assert "omo" in core._PRIVILEGED_COMMANDS
    assert gateway.handle("telegram", "42", "/omo help").startswith("OMO session control")
    assert gateway.handle("telegram", "99", "/omo help") == "OMO control is restricted to configured Telegram chat IDs."
    assert gateway.handle("http", "42", "/omo help").startswith("OMO session control")
    gateway.shutdown()
    assert rpc.closed


def test_parser_and_session_command_preserve_omo_contract() -> None:
    assert parse_omo_command("/omo@BirkinBot send hello") == ("send", "hello")
    assert parse_omo_command("/other") is None
    assert command_for_session(("omo", "--no-session", "--approve"), Path("C:/sessions/example.jsonl")) == ("omo", "--approve", "--session", "C:\\sessions\\example.jsonl")


def test_rpc_client_uses_jsonl_protocol() -> None:
    program = """import json,sys\nfor line in sys.stdin:\n request=json.loads(line); data={'text':'done'} if request['type']=='get_last_assistant_text' else {}; print(json.dumps({'id':request['id'],'type':'response','success':True,'data':data}),flush=True); print(json.dumps({'type':'agent_settled'}),flush=True)"""
    client = OmoRpcClient(command=(sys.executable, "-u", "-c", program), timeout=5)
    try:
        client.switch_session(Path("C:/sessions/example.jsonl"))
        assert client.prompt("hello") == "done"
        client.steer("change direction")
        client.abort()
    finally:
        client.close()
