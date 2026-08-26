from __future__ import annotations

import ctypes
import json
import secrets
import subprocess
import sys
import uuid
from ctypes import wintypes
from pathlib import Path
from typing import Protocol, cast

import pytest

from tests.native_windows_request_success import request_success
from tests.native_windows_terminal_bridge_support import (
    WindowsTerminalBridgeHarness,
    command_bytes,
    event_payloads,
)

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="native Windows terminal runtime publication",
)


class _KernelCall(Protocol):
    argtypes: list[object]
    restype: object

    def __call__(self, *args: object) -> int: ...


def _kernel_call(name: str) -> _KernelCall:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    return cast(_KernelCall, cast(object, getattr(kernel32, name)))


def test_sensitive_cmd_value_never_enters_live_journal_snapshot_or_reconnect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given an authenticated bridge and a memory-only sensitive value
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    harness = WindowsTerminalBridgeHarness(tmp_path, auto_approve=True)
    value = f"private-{secrets.token_hex(16)}"
    try:
        _, _ = harness.connect()
        opened, _ = harness.create("create-sensitive")
        terminal_id, lease = str(opened["terminal_id"]), str(opened["lease"])
        # When the literal is assigned, expanded later, and ordinary history follows
        assigned_after = harness.current_cursor
        assigned_receipt, assigned = request_success(harness, "terminal.input", "assign-sensitive", {
            "terminal_id": terminal_id, "lease": lease, "sequence": 1,
            "data": f"set PASSWORD={value}\r\n",
        })
        _ = harness.await_output(terminal_id, "[REDACTED]", after_cursor=assigned_after)
        assert assigned_receipt.kind == "receipt"
        expanded_after = assigned_receipt.body["result_event_cursor"]
        assert isinstance(expanded_after, int) and not isinstance(expanded_after, bool)
        assert harness.current_cursor >= expanded_after
        expanded_receipt, expanded = request_success(harness, "terminal.input", "expand-sensitive", {
            "terminal_id": terminal_id, "lease": lease, "sequence": 2,
            "data": "echo %PASSWORD%\r\n",
        })
        _ = harness.await_output(terminal_id, "[REDACTED]", after_cursor=expanded_after)
        assert expanded_receipt.kind == "receipt"
        visible_after = expanded_receipt.body["result_event_cursor"]
        assert isinstance(visible_after, int) and not isinstance(visible_after, bool)
        assert harness.current_cursor >= visible_after
        visible_receipt, visible = request_success(harness, "terminal.input", "assign-visible", {
            "terminal_id": terminal_id, "lease": lease, "sequence": 3,
            "data": command_bytes(b"VISIBLE"),
        })
        _ = harness.await_output(terminal_id, "VISIBLE", after_cursor=visible_after)
        assert visible_receipt.kind == "receipt"
        result_cursor = visible_receipt.body["result_event_cursor"]
        assert isinstance(result_cursor, int) and not isinstance(result_cursor, bool)
        assert harness.current_cursor >= result_cursor
        snapshot, _ = request_success(harness, "terminal.snapshot", "snapshot-sensitive", {
            "terminal_id": terminal_id,
        })
        durable = (tmp_path / "journal" / "session-1" / "events.jsonl").read_bytes()
        public = json.dumps(
            [event.body for event in assigned + expanded + visible],
            ensure_ascii=False,
        )
        # Then all sensitive surfaces mask every occurrence while ordinary bytes remain
        assert value not in public
        assert value.encode() not in durable
        assert value not in json.dumps(snapshot.body, ensure_ascii=False)
        assert "[REDACTED]" in public
        assert "VISIBLE" in public
        harness.disconnect()
        _, reconnect = harness.connect()
        assert value not in json.dumps(reconnect.body, ensure_ascii=False)
        assert "VISIBLE" in json.dumps(reconnect.body, ensure_ascii=False)
    finally:
        harness.close()


def test_first_input_uses_observed_prompt_cursor_after_create(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    harness = WindowsTerminalBridgeHarness(tmp_path, auto_approve=True)
    try:
        _, _ = harness.connect()
        opened, _ = harness.create("create-prompt-barrier")
        prompt_cursor = harness.current_cursor
        terminal_id, lease = str(opened["terminal_id"]), str(opened["lease"])
        receipt, _ = request_success(harness, "terminal.input", "first-after-prompt", {
            "terminal_id": terminal_id,
            "lease": lease,
            "sequence": 1,
            "data": command_bytes(b"FIRST_AFTER_PROMPT"),
        })
        assert receipt.kind == "receipt", receipt.body
        assert receipt.body["accepted_cursor"] == prompt_cursor + 1
    finally:
        harness.close()


def test_named_event_delayed_output_and_exit_arrive_without_snapshot_or_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a bridge subscription and child command blocked on an owned kernel event
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    harness = WindowsTerminalBridgeHarness(tmp_path, auto_approve=True)
    event_name = f"Local\\BirkinRuntime-{uuid.uuid4().hex}"
    marker = b"DELAYED_RUNTIME_MARKER"
    create_event = _kernel_call("CreateEventW")
    create_event.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    create_event.restype = wintypes.HANDLE
    set_event = _kernel_call("SetEvent")
    set_event.argtypes = [wintypes.HANDLE]
    set_event.restype = wintypes.BOOL
    close_handle = _kernel_call("CloseHandle")
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    event_handle = create_event(None, True, False, event_name)
    assert event_handle
    try:
        _, _ = harness.connect()
        opened, _ = harness.create("create-delayed")
        terminal_id, lease = str(opened["terminal_id"]), str(opened["lease"])
        encoded = marker.hex()
        script = (
            "import ctypes;from ctypes import wintypes;"
            "k=ctypes.WinDLL('kernel32');"
            "k.OpenEventW.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.LPCWSTR];"
            "k.OpenEventW.restype=wintypes.HANDLE;"
            f"h=k.OpenEventW(0x100000,False,{event_name!r});"
            "k.WaitForSingleObject(h,10000);"
            f"print(bytes.fromhex('{encoded}').decode(),flush=True);k.CloseHandle(h)"
        )
        command = subprocess.list2cmdline([sys.executable, "-c", script]) + " && exit 9\r\n"
        # When input returns before the child is released, then the event is triggered
        _, before_release = request_success(harness, "terminal.input", "arm-delayed", {
            "terminal_id": terminal_id, "lease": lease, "sequence": 1, "data": command,
        })
        assert not event_payloads(before_release, "terminal.exited")
        assert set_event(event_handle)
        output = harness.receive_event("terminal.output", terminal_id)
        exited = harness.receive_event("terminal.exited", terminal_id)
        # Then delayed output precedes one natural exit without a follow-up request
        assert marker.decode() in str(output.body["payload"])
        exit_payload = exited.body["payload"]
        assert isinstance(exit_payload, dict)
        assert exit_payload["exit_status"] == 9
        assert sum(event.type == "terminal.exited" for event in harness.source.events()) == 1
    finally:
        assert close_handle(event_handle)
        harness.close()
