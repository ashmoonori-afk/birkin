"""Owned bridge harness for the native Windows terminal scenario."""

from __future__ import annotations

import socket
import subprocess
import sys
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import final

from birkin.native.capability import BootstrapSecretStore
from birkin.native.protocol import JSONValue, NativeEnvelope, encode_frame
from birkin.native.server import NativeBridgeServer
from birkin.native.transport import receive_frame
from birkin.workspace.owned_terminal import TerminalAuthority
from birkin.workspace.service import WorkspaceService
from tests.native_bridge_support import envelope, hello, local_peer_uid, serve

TIMEOUT = 10.0


@final
class WindowsTerminalBridgeHarness:
    """Own one test bridge, authority, connection, and terminal process tree."""

    def __init__(self, root: Path, *, auto_approve: bool) -> None:
        self.root = root
        self.source = WorkspaceService(
            root=root / "journal", session_id="session-1", handlers={}
        )
        self.terminal = TerminalAuthority(
            session_id="session-1",
            workspace_root=root,
            emit=self.source.emit,
            config_loader=lambda: {
                "auto_approve": ["shell"] if auto_approve else []
            },
        )
        self.source.set_handlers(self.terminal.handlers())
        self.bridge = NativeBridgeServer(
            self.source,
            capabilities=BootstrapSecretStore(root / "native"),
            instance_id="instance-windows-terminal",
            server_version="1.0.0",
            heartbeat_interval=0.05,
            peer_timeout=1.0,
            on_disconnect=self.terminal.revoke_leases,
        )
        self.client: socket.socket | None = None
        self.thread: threading.Thread | None = None
        self.errors: list[BaseException] = []
        self.token = ""

    def connect(self) -> tuple[NativeEnvelope, NativeEnvelope]:
        server_socket, client = socket.socketpair()
        client.settimeout(TIMEOUT)
        thread, errors = serve(
            self.bridge,
            server_socket,
            transport="uds",
            peer_uid=local_peer_uid(),
        )
        self.client, self.thread, self.errors = client, thread, errors
        client.sendall(encode_frame(hello(
            bootstrap_secret=None,
            surface="windows",
            view_id="terminal",
        )))
        ready = receive_frame(client)
        capability = ready.body["capability"]
        assert isinstance(capability, dict)
        token = capability["token"]
        assert isinstance(token, str)
        self.token = token
        client.sendall(encode_frame(envelope(
            "subscribe",
            frame_id="subscribe-terminal",
            body={
                "session_id": "session-1",
                "after_cursor": 0,
                "known_instance_id": None,
                "session_capability": token,
                "surfaces": {},
            },
        )))
        while True:
            snapshot = receive_frame(client)
            if snapshot.kind == "snapshot":
                return ready, snapshot
            assert snapshot.kind == "ping"
            self._pong(client, snapshot)

    def disconnect(self) -> None:
        if self.client is not None:
            self.client.close()
        if self.thread is not None:
            self.thread.join(timeout=TIMEOUT)
            assert not self.thread.is_alive()
        assert self.errors == []
        self.client, self.thread = None, None

    def request(
        self,
        command_type: str,
        command_id: str,
        payload: dict[str, object],
    ) -> tuple[NativeEnvelope, list[NativeEnvelope]]:
        assert self.client is not None
        self.client.sendall(encode_frame(envelope(
            "command",
            frame_id=command_id,
            body={
                "session_capability": self.token,
                "command": {
                    "protocol_version": 1,
                    "command_id": command_id,
                    "expected_cursor": self.source.snapshot().cursor,
                    "type": command_type,
                    "payload": payload,
                    "client_context": {
                        "surface": "windows",
                        "view_id": "terminal",
                    },
                },
            },
        )))
        events: list[NativeEnvelope] = []
        response: NativeEnvelope | None = None
        completion_type = ""
        while True:
            message = receive_frame(self.client)
            if message.kind == "event":
                events.append(message)
            if message.kind == "ping":
                self._pong(self.client, message)
            if message.in_reply_to == command_id and message.kind in {
                "receipt", "error"
            }:
                response = message
                completion_type = (
                    "command.completed"
                    if response.kind == "receipt"
                    else "command.failed"
                )
            if (
                response is not None
                and message.kind == "event"
                and message.body.get("type") == completion_type
                and message.body.get("command_id") == command_id
            ):
                return response, events

    def create(
        self,
        command_id: str,
    ) -> tuple[Mapping[str, JSONValue], list[NativeEnvelope]]:
        receipt, events = self.request(
            "terminal.create",
            command_id,
            {"actor_kind": "native_human", "cwd": str(self.root)},
        )
        return receipt_result(receipt), events

    def close(self) -> None:
        self.terminal.close_all()
        self.disconnect()
        assert self.terminal.active_process_ids == ()

    def _pong(self, client: socket.socket, ping: NativeEnvelope) -> None:
        client.sendall(encode_frame(envelope(
            "pong",
            frame_id=f"pong-{ping.id}",
            in_reply_to=ping.id,
            body={**ping.body, "session_capability": self.token},
        )))


def receipt_result(receipt: NativeEnvelope) -> Mapping[str, JSONValue]:
    assert receipt.kind == "receipt", receipt.body
    value = receipt.body.get("result")
    assert isinstance(value, dict)
    return value


def event_payloads(
    events: list[NativeEnvelope],
    event_type: str,
) -> list[Mapping[str, JSONValue]]:
    values: list[Mapping[str, JSONValue]] = []
    for event in events:
        if event.body.get("type") == event_type:
            payload = event.body.get("payload")
            assert isinstance(payload, dict)
            values.append(payload)
    return values


def command_bytes(data: bytes) -> str:
    values = ",".join(str(value) for value in data)
    return subprocess.list2cmdline([
        sys.executable,
        "-c",
        f"import sys;sys.stdout.buffer.write(bytes([{values}]))",
    ]) + "\r\n"
