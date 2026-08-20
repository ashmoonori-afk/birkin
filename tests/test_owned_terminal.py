from __future__ import annotations

import os
import signal
from pathlib import Path
from typing import Any

import pytest

from birkin import approvals, store
from birkin.workspace.contracts import (
    TerminalApprovalRequired,
    TerminalLeaseRequired,
    TerminalSignalRejected,
)
from birkin.workspace.owned_terminal import TerminalAuthority


class EventRecorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def __call__(self, kind: str, payload: dict[str, object]) -> Any:
        self.events.append((kind, payload))
        return payload


def authority(tmp_path: Path, recorder: EventRecorder, cfg: dict[str, Any]) -> TerminalAuthority:
    return TerminalAuthority(
        session_id="session-1",
        workspace_root=tmp_path,
        emit=recorder,
        config_loader=lambda: cfg,
    )


def test_terminal_create_requires_shell_approval_before_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    recorder = EventRecorder()
    terminal = authority(tmp_path, recorder, {"auto_approve": []})

    with pytest.raises(TerminalApprovalRequired) as caught:
        terminal.create({"actor_kind": "native_human", "cwd": str(tmp_path)})

    pending = store.get_pending(caught.value.approval_id)
    assert pending is not None
    assert pending["category"] == "shell"
    assert pending["status"] == "pending"
    requested = next(payload for kind, payload in recorder.events if kind == "approval.requested")
    assert requested["approval_id"] == pending["id"]
    assert requested["risk"] == "high"
    assert requested["sealed"] is False
    assert requested["decided"] is False
    assert not any(kind == "terminal.opened" for kind, _ in recorder.events)
    assert terminal.active_process_ids == ()


def test_revoked_terminal_lease_cannot_be_replayed_as_empty_string(
    tmp_path: Path,
) -> None:
    recorder = EventRecorder()
    terminal = authority(tmp_path, recorder, {"auto_approve": ["shell"]})
    opened = terminal.create({"actor_kind": "native_human", "cwd": str(tmp_path)})
    terminal.revoke_leases()
    try:
        with pytest.raises(TerminalLeaseRequired, match="live terminal lease"):
            terminal.input({
                "terminal_id": opened["terminal_id"],
                "lease": "",
                "sequence": 1,
                "data": "echo bypassed-revocation\n",
            })
    finally:
        terminal.close_all()


def test_terminal_approval_can_mint_only_one_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    recorder = EventRecorder()
    terminal = authority(tmp_path, recorder, {"auto_approve": []})
    with pytest.raises(TerminalApprovalRequired) as caught:
        terminal.create({"actor_kind": "native_human", "cwd": str(tmp_path)})
    assert approvals.approve(caught.value.approval_id)["ok"] is True

    first = terminal.create({
        "actor_kind": "native_human",
        "cwd": str(tmp_path),
        "approval_id": caught.value.approval_id,
    })
    try:
        assert first["lease"]
        with pytest.raises(TerminalApprovalRequired):
            terminal.create({
                "actor_kind": "native_human",
                "cwd": str(tmp_path),
                "approval_id": caught.value.approval_id,
            })
    finally:
        terminal.close_all()


def test_terminal_create_refuses_missing_or_wrong_lease(tmp_path: Path) -> None:
    recorder = EventRecorder()
    terminal = authority(tmp_path, recorder, {"auto_approve": ["shell"]})
    opened = terminal.create({"actor_kind": "native_human", "cwd": str(tmp_path)})
    try:
        with pytest.raises(TerminalLeaseRequired):
            terminal.input({
                "terminal_id": opened["terminal_id"],
                "lease": "wrong",
                "sequence": 1,
                "data": "echo bypass\n",
            })
    finally:
        terminal.close_all()


def test_real_pty_echo_resize_snapshot_signal_and_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    recorder = EventRecorder()
    terminal = authority(tmp_path, recorder, {"auto_approve": ["shell"]})
    opened = terminal.create({"actor_kind": "native_human", "cwd": str(tmp_path)})
    terminal_id = str(opened["terminal_id"])
    lease = str(opened["lease"])
    raw_pid = opened["pid"]
    assert isinstance(raw_pid, int)
    pid = raw_pid
    try:
        result = terminal.input({
            "terminal_id": terminal_id,
            "lease": lease,
            "sequence": 1,
            "data": "printf 'hello-native\\n'\n",
        })
        assert "hello-native" in str(result["output"])
        assert len(str(result["output"]).encode()) <= terminal.max_output_bytes

        resized = terminal.resize({
            "terminal_id": terminal_id,
            "lease": lease,
            "columns": 100,
            "rows": 30,
        })
        assert resized == {"terminal_id": terminal_id, "columns": 100, "rows": 30}

        snapshot = terminal.snapshot({"terminal_id": terminal_id})
        assert "hello-native" in str(snapshot["screen"])
        assert len(str(snapshot["screen"]).encode()) <= terminal.max_screen_bytes

        signalled = terminal.signal({
            "terminal_id": terminal_id,
            "lease": lease,
            "signal": "INT",
        })
        assert signalled["signal"] == "INT"
        with pytest.raises(TerminalSignalRejected):
            terminal.signal({
                "terminal_id": terminal_id,
                "lease": lease,
                "signal": "SEGV",
            })

        closed = terminal.close({"terminal_id": terminal_id, "lease": lease})
        assert closed["closed"] is True
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    finally:
        terminal.close_all()

    event_types = [kind for kind, _ in recorder.events]
    assert "terminal.opened" in event_types
    assert "terminal.input" in event_types
    assert "terminal.output" in event_types
    assert "terminal.resized" in event_types
    assert "terminal.receipt" in event_types
    assert "terminal.exited" in event_types


def test_lease_expiry_revokes_input_and_process_tree(tmp_path: Path) -> None:
    recorder = EventRecorder()
    now = [100.0]
    terminal = TerminalAuthority(
        session_id="session-1",
        workspace_root=tmp_path,
        emit=recorder,
        config_loader=lambda: {"auto_approve": ["shell"]},
        monotonic=lambda: now[0],
        lease_ttl=1.0,
    )
    opened = terminal.create({"actor_kind": "native_human", "cwd": str(tmp_path)})
    raw_pid = opened["pid"]
    assert isinstance(raw_pid, int)
    pid = raw_pid
    now[0] = 102.0

    with pytest.raises(TerminalLeaseRequired, match="expired"):
        terminal.input({
            "terminal_id": opened["terminal_id"],
            "lease": opened["lease"],
            "sequence": 1,
            "data": "echo refused\n",
        })

    with pytest.raises(ProcessLookupError):
        os.kill(pid, signal.SIGCONT)
    terminal.close_all()
