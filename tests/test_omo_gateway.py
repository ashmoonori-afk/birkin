from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import cast

import birkin.omo_rpc as omo_rpc
from birkin.gateway import core
from birkin.omo import OmoController, parse_omo_command
from birkin.omo_rpc import OmoRpcClient, OmoState, command_for_session


class FakeRpc:
    def __init__(self) -> None:
        self.selected: Path | None = None
        self.prompts: list[str] = []
        self.prompt_called = threading.Event()
        self.steers: list[str] = []
        self.aborted = False
        self.closed = False

    def switch_session(self, path: Path) -> None:
        self.selected = path

    def prompt(self, message: str) -> str:
        self.prompts.append(message)
        self.prompt_called.set()
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


class BlockingRpc(FakeRpc):
    def __init__(self) -> None:
        super().__init__()
        self.prompt_started = threading.Event()
        self.release_prompt = threading.Event()
        self.prompt_finished = threading.Event()

    def prompt(self, message: str) -> str:
        self.prompts.append(message)
        self.prompt_called.set()
        self.prompt_started.set()
        if not self.release_prompt.wait(timeout=5):
            raise AssertionError("test did not release the blocked OMO prompt")
        self.prompt_finished.set()
        return f"reply: {message}"


class FailingRpc(FakeRpc):
    def __init__(self) -> None:
        super().__init__()
        self.prompt_failed = threading.Event()

    def prompt(self, message: str) -> str:
        self.prompts.append(message)
        self.prompt_called.set()
        try:
            raise OSError("background prompt failed")
        finally:
            self.prompt_failed.set()


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
    assert controller.handle("/omo send fix the test").startswith(
        "OMO prompt started in the background."
    )
    assert rpc.prompt_called.wait(timeout=1)
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


def test_gateway_keeps_omo_controls_available_while_send_runs(
    monkeypatch, tmp_path: Path,
) -> None:
    write_session(tmp_path, "abc12345-0000", "C:/repo/one")
    rpc = BlockingRpc()
    controller = OmoController(rpc=rpc, session_roots=(tmp_path,))
    monkeypatch.setattr(core, "OmoController", lambda: controller)
    monkeypatch.setattr(core, "build_session", lambda cfg: object())
    gateway = core.Gateway(
        {"channels": {"telegram": {"allowed_chat_ids": ["42"]}}}
    )

    assert gateway.handle("telegram", "42", "/omo use abc123").startswith("Selected")

    try:
        assert gateway.handle(
            "telegram", "42", "/omo send fix the test"
        ) == (
            "OMO prompt started in the background. "
            "Use /omo status, /omo steer, /omo abort, or /omo last."
        )
        assert rpc.prompt_started.wait(timeout=1)
        assert gateway.handle(
            "telegram", "42", "/omo steer check caller"
        ) == "Steering message queued."
        assert gateway.handle(
            "telegram", "42", "/omo abort"
        ) == "Abort requested."
    finally:
        rpc.release_prompt.set()
        assert rpc.prompt_finished.wait(timeout=1)
        gateway.shutdown()

    assert rpc.steers == ["check caller"]
    assert rpc.aborted


def test_controller_rejects_conflicting_operations_while_send_runs(
    tmp_path: Path,
) -> None:
    write_session(tmp_path, "abc12345-0000", "C:/repo/one")
    write_session(tmp_path, "def67890-0000", "C:/repo/two")
    rpc = BlockingRpc()
    controller = OmoController(rpc=rpc, session_roots=(tmp_path,))

    assert controller.handle("/omo use abc123").startswith("Selected")
    assert controller.handle("/omo send first").startswith(
        "OMO prompt started in the background."
    )
    try:
        assert rpc.prompt_started.wait(timeout=1)
        assert controller.handle("/omo send second") == (
            "An OMO prompt is already running."
        )
        assert controller.handle("/omo use def678") == (
            "Wait for the running OMO prompt to finish before switching sessions."
        )
    finally:
        rpc.release_prompt.set()
        assert rpc.prompt_finished.wait(timeout=1)
        controller.close()


def test_controller_reports_background_prompt_failure(tmp_path: Path) -> None:
    write_session(tmp_path, "abc12345-0000", "C:/repo/one")
    rpc = FailingRpc()
    controller = OmoController(rpc=rpc, session_roots=(tmp_path,))

    assert controller.handle("/omo use abc123").startswith("Selected")
    assert controller.handle("/omo send fail").startswith(
        "OMO prompt started in the background."
    )
    assert rpc.prompt_failed.wait(timeout=1)
    prompt_thread = controller._prompt_thread
    assert prompt_thread is not None
    prompt_thread.join(timeout=1)
    assert not prompt_thread.is_alive()
    assert "Last prompt error: background prompt failed" in controller.handle(
        "/omo status"
    )
    controller.close()


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


def test_rpc_client_kills_process_tree_after_close_timeout(monkeypatch) -> None:
    class HungProcess:
        stdin = None
        waits = 0

        def poll(self) -> None:
            return None

        def wait(self, timeout: float) -> None:
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired("omo", timeout)

    process = HungProcess()
    killed: list[HungProcess] = []
    client = OmoRpcClient(command=("omo",))
    client._process = cast(subprocess.Popen[str], cast(object, process))
    monkeypatch.setattr(
        omo_rpc,
        "kill_tree",
        lambda selected: killed.append(selected),
        raising=False,
    )

    client.close()

    assert killed == [process]
