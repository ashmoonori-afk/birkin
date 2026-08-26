from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import psutil
import pytest

from birkin.workspace.contracts import REDACTION_MARKER
from tests.native_windows_terminal_bridge_support import (
    TIMEOUT,
    WindowsTerminalBridgeHarness,
    command_bytes,
    event_payloads,
    receipt_result,
)

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="native Windows terminal authority requires ConPTY",
)


def test_windows_bridge_round_trip_redacts_and_bounds_terminal_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given an auto-approved Windows terminal and a subscribed bridge stream
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    harness = WindowsTerminalBridgeHarness(tmp_path, auto_approve=True)
    secret = "BIRKIN_INPUT_SECRET_WAVE03"
    child_pid = 0
    try:
        ready, _ = harness.connect()
        capabilities = ready.body["capabilities"]
        assert isinstance(capabilities, dict)
        commands = capabilities["commands"]
        assert isinstance(commands, list) and "terminal.create" in commands
        # When create/input/resize/signal/close traverse the real bridge and ConPTY
        result, opened_events = harness.create("create")
        lease, terminal_id = str(result["lease"]), str(result["terminal_id"])
        opened = event_payloads(opened_events, "terminal.opened")
        assert opened and opened[0]["lease"] == REDACTION_MARKER

        _, first_events = harness.request("terminal.input", "input-ok", {
            "terminal_id": terminal_id, "lease": lease, "sequence": 1,
            "data": command_bytes(b"CONPTY_OK"),
        })
        assert "CONPTY_OK" in str(event_payloads(first_events, "terminal.output"))
        stale, _ = harness.request("terminal.input", "input-stale", {
            "terminal_id": terminal_id, "lease": lease, "sequence": 1,
            "data": secret,
        })
        assert stale.body["code"] == "E_TERMINAL_SEQUENCE"

        split = "한글-日本語".encode()
        _, _ = harness.request("terminal.input", "input-unicode-vt", {
            "terminal_id": terminal_id, "lease": lease, "sequence": 2,
            "data": command_bytes(split + b"\x1b[31mRED\x1b[0m"),
        })
        large_command = subprocess.list2cmdline([
            sys.executable,
            "-c",
            "import sys;sys.stdout.buffer.write(b'A'*20000+b'BOUNDARY_OK')",
        ]) + "\r\n"
        _, large_events = harness.request("terminal.input", "input-bounded", {
            "terminal_id": terminal_id, "lease": lease, "sequence": 3,
            "data": large_command,
        })
        output_payloads = event_payloads(large_events, "terminal.output")
        assert all(
            len(str(payload["data"]).encode())
            <= harness.terminal.max_output_bytes
            for payload in output_payloads
        )
        resized, _ = harness.request("terminal.resize", "resize", {
            "terminal_id": terminal_id, "lease": lease,
            "columns": 100, "rows": 30,
        })
        assert receipt_result(resized) == {
            "terminal_id": terminal_id, "columns": 100, "rows": 30
        }
        for name in ("TERM", "HUP"):
            refused, _ = harness.request("terminal.signal", f"signal-{name}", {
                "terminal_id": terminal_id, "lease": lease, "signal": name,
            })
            assert refused.body["code"] == "E_TERMINAL_SIGNAL"
        interrupted, _ = harness.request("terminal.signal", "signal-INT", {
            "terminal_id": terminal_id, "lease": lease, "signal": "INT",
        })
        assert receipt_result(interrupted)["signal"] == "INT"
        snapshot, _ = harness.request("terminal.snapshot", "snapshot", {
            "terminal_id": terminal_id,
        })
        projected = receipt_result(snapshot)
        screen = str(projected["screen"])
        assert "한글-日本語" in screen and "\x1b[31mRED" in screen
        assert "\x1b[0m" in screen or "\x1b[m" in screen
        assert len(screen.encode()) <= harness.terminal.max_screen_bytes

        child_code = (
            "import subprocess,sys,threading;"
            "p=subprocess.Popen([sys.executable,'-c','import threading;threading.Event().wait()']);"
            "print('BIRKIN_CHILD_PID='+str(p.pid),flush=True);p.wait()"
        )
        _, child_events = harness.request("terminal.input", "input-child", {
            "terminal_id": terminal_id, "lease": lease, "sequence": 4,
            "data": subprocess.list2cmdline([
                sys.executable, "-c", child_code
            ]) + "\r\n",
        })
        matched = re.search(
            r"BIRKIN_CHILD_PID=(\d+)",
            str(event_payloads(child_events, "terminal.output")),
        )
        assert matched is not None
        child_pid = int(matched.group(1))
        raw_pid = result["pid"]
        assert isinstance(raw_pid, int) and not isinstance(raw_pid, bool)
        process = psutil.Process(raw_pid)
        child_process = psutil.Process(child_pid)
        closed, exit_events = harness.request("terminal.close", "close", {
            "terminal_id": terminal_id, "lease": lease,
        })
        assert receipt_result(closed)["closed"] is True
        assert len(event_payloads(exit_events, "terminal.exited")) == 1
        _ = process.wait(timeout=TIMEOUT)
        _ = child_process.wait(timeout=TIMEOUT)
        durable = str(harness.source.events()) + str(
            harness.source.snapshot().to_json()
        )
        assert lease not in durable and secret not in durable
        input_events = [
            event.payload
            for event in harness.source.events()
            if event.type == "terminal.input"
        ]
        assert "data': '" not in str(input_events)

        second_result, _ = harness.create("create-reconnect")
        old_lease = str(second_result["lease"])
        second_id = str(second_result["terminal_id"])
        harness.disconnect()
        _, reconnected = harness.connect()
        terminals = reconnected.body["terminals"]
        assert isinstance(terminals, list) and terminals
        replay = next(
            item
            for item in terminals
            if isinstance(item, dict) and item.get("terminal_id") == second_id
        )
        assert replay["lease"] is None and replay["read_only"] is True
        stale_lease, _ = harness.request("terminal.input", "stale-lease", {
            "terminal_id": second_id, "lease": old_lease, "sequence": 1,
            "data": "echo rejected\r\n",
        })
        assert stale_lease.body["code"] == "E_TERMINAL_LEASE_REQUIRED"
    finally:
        harness.close()
        if child_pid and psutil.pid_exists(child_pid):
            psutil.Process(child_pid).kill()
