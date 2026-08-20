from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import cast

import pytest

from birkin.native.capability import BootstrapSecretStore
from birkin.native.protocol import encode_frame
from birkin.native.server import NativeBridgeServer
from birkin.native.session import NativeProjectionSession
from birkin.workspace.contracts import TerminalLeaseRequired
from birkin.workspace.owned_terminal import TerminalAuthority
from birkin.workspace.service import WorkspaceService
from tests.native_bridge_support import (
    envelope,
    handshake,
    local_peer_uid,
    receive_kind,
    serve,
)


def _send(
    client: socket.socket,
    token: str,
    source: WorkspaceService,
    command_type: str,
    command_id: str,
    payload: dict[str, object],
) -> None:
    client.sendall(encode_frame(envelope(
        "command",
        frame_id=command_id,
        body={
            "session_capability": token,
            "command": {
                "protocol_version": 1,
                "command_id": command_id,
                "expected_cursor": source.snapshot().cursor,
                "type": command_type,
                "payload": payload,
                "client_context": {"surface": "macos", "view_id": "terminal"},
            },
        },
    )))


def _event(client: socket.socket, event_type: str) -> dict[str, object]:
    for _ in range(16):
        message = receive_kind(client, "event")
        if message.body["type"] == event_type:
            return cast(dict[str, object], message.body["payload"])
    raise AssertionError(f"missing {event_type}")


def _bridge(
    tmp_path: Path, cfg: dict[str, object]
) -> tuple[NativeBridgeServer, WorkspaceService, TerminalAuthority]:
    source = WorkspaceService(
        root=tmp_path / "journal", session_id="session-1", handlers={}
    )
    terminal = TerminalAuthority(
        session_id="session-1",
        workspace_root=tmp_path,
        emit=source.emit,
        config_loader=lambda: cfg,
    )
    source.set_handlers(terminal.handlers())
    bridge = NativeBridgeServer(
        source,
        capabilities=BootstrapSecretStore(tmp_path / "native"),
        instance_id="instance-terminal",
        server_version="1.0.0",
        on_disconnect=terminal.revoke_leases,
    )
    return bridge, source, terminal


def test_full_native_bridge_real_pty_round_trip_and_invalid_signal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    bridge, source, terminal = _bridge(tmp_path, {"auto_approve": ["shell"]})
    server_socket, client = socket.socketpair()
    thread, errors = serve(
        bridge, server_socket, transport="uds", peer_uid=local_peer_uid()
    )
    pid = 0
    try:
        token = handshake(client)
        _send(client, token, source, "terminal.create", "create-terminal", {
            "actor_kind": "native_human", "cwd": str(tmp_path),
        })
        create_receipt = receive_kind(client, "receipt")
        assert create_receipt.body["state"] == "completed"
        result = cast(dict[str, object], create_receipt.body["result"])
        lease = str(result["lease"])
        opened = _event(client, "terminal.opened")
        assert opened["lease"] == "[REDACTED]"
        replay = NativeProjectionSession(
            source, instance_id="instance-terminal"
        ).subscribe(after_cursor=0, known_instance_id="instance-terminal")
        replay_text = str(replay.events)
        assert lease not in replay_text
        assert "[REDACTED]" in replay_text
        terminal_id = str(opened["terminal_id"])
        raw_pid = opened["pid"]
        assert isinstance(raw_pid, int)
        pid = raw_pid

        _send(client, token, source, "terminal.input", "input-terminal", {
            "terminal_id": terminal_id,
            "lease": lease,
            "sequence": 1,
            "data": "printf 'hello-native\\n'\n",
        })
        assert receive_kind(client, "receipt").body["state"] == "completed"
        output = _event(client, "terminal.output")
        assert "hello-native" in str(output["data"])

        _send(client, token, source, "terminal.signal", "bad-signal", {
            "terminal_id": terminal_id,
            "lease": lease,
            "signal": "SEGV",
        })
        refused = receive_kind(client, "error")
        assert refused.body["code"] == "E_TERMINAL_SIGNAL"

        _send(client, token, source, "terminal.close", "close-terminal", {
            "terminal_id": terminal_id, "lease": lease,
        })
        assert receive_kind(client, "receipt").body["state"] == "completed"
    finally:
        terminal.close_all()
        client.close()
        thread.join(timeout=2)
    assert errors == []
    assert terminal.active_process_ids == ()
    if pid:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


def test_disconnect_revokes_terminal_mutation_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    bridge, source, terminal = _bridge(tmp_path, {"auto_approve": ["shell"]})
    server_socket, client = socket.socketpair()
    thread, errors = serve(
        bridge, server_socket, transport="uds", peer_uid=local_peer_uid()
    )
    opened: dict[str, object] = {}
    try:
        token = handshake(client)
        _send(client, token, source, "terminal.create", "disconnect-terminal", {
            "actor_kind": "native_human", "cwd": str(tmp_path),
        })
        assert receive_kind(client, "receipt").body["state"] == "completed"
        opened = _event(client, "terminal.opened")
        client.close()
        thread.join(timeout=2)
        with pytest.raises(TerminalLeaseRequired):
            terminal.input({
                "terminal_id": opened["terminal_id"],
                "lease": opened["lease"],
                "sequence": 1,
                "data": "echo refused\\n",
            })
    finally:
        terminal.close_all()
        client.close()
        thread.join(timeout=2)
    assert errors == []


def test_bridge_refuses_terminal_lease_until_shell_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    bridge, source, terminal = _bridge(tmp_path, {"auto_approve": []})
    server_socket, client = socket.socketpair()
    thread, errors = serve(
        bridge, server_socket, transport="uds", peer_uid=local_peer_uid()
    )
    try:
        token = handshake(client)
        _send(client, token, source, "terminal.create", "approval-terminal", {
            "actor_kind": "native_human", "cwd": str(tmp_path),
        })
        refused = receive_kind(client, "error")
        assert refused.body["code"] == "E_TERMINAL_APPROVAL_REQUIRED"
        assert isinstance(refused.body["approval_id"], str)
        assert terminal.active_process_ids == ()
    finally:
        terminal.close_all()
        client.close()
        thread.join(timeout=2)
    assert errors == []
