from __future__ import annotations

import socket
import subprocess
import sys
import threading
import time
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
from tests.native_windows_event_ledger import BoundedEventLedger
from tests.native_windows_prompt_terminator import await_prompt_terminator

TIMEOUT = 10.0


@final
class WindowsTerminalBridgeHarness:
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
        self.ledger = BoundedEventLedger()

    @property
    def current_cursor(self) -> int:
        return self.ledger.cursor

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
        deadline = time.monotonic() + TIMEOUT
        ready = self._read(deadline)
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
            snapshot = self._read(deadline)
            if snapshot.kind == "snapshot":
                cursor = snapshot.body.get("cursor")
                assert isinstance(cursor, int) and not isinstance(cursor, bool)
                self.ledger.reset(cursor)
                return ready, snapshot

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
        *,
        expected_cursor: int | None = None,
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
                    "expected_cursor": (
                        self.ledger.cursor
                        if expected_cursor is None
                        else expected_cursor
                    ),
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
        deadline = time.monotonic() + TIMEOUT
        while True:
            message = self._read(deadline)
            if message.kind == "event":
                events.append(message)
            if message.in_reply_to == command_id and message.kind in {
                "receipt", "error"
            }:
                response = message
                completion_type = (
                    "command.completed"
                    if response.kind == "receipt"
                    else "command.failed"
                )
            if response is not None:
                accepted_cursor = response.body.get("accepted_cursor")
                result_cursor = response.body.get("result_event_cursor")
                accepted_failure = (
                    isinstance(accepted_cursor, int) and not isinstance(accepted_cursor, bool)
                    and isinstance(result_cursor, int) and not isinstance(result_cursor, bool)
                )
                if response.kind == "error":
                    if not accepted_failure:
                        return response, events
                    assert isinstance(result_cursor, int) and not isinstance(result_cursor, bool)
                    if self.ledger.cursor >= result_cursor:
                        return response, events
                if any(
                    event.body.get("type") == completion_type
                    and event.body.get("command_id") == command_id
                    for event in events
                ):
                    result_cursor = response.body.get("result_event_cursor")
                    if response.kind == "receipt":
                        assert isinstance(result_cursor, int) and not isinstance(result_cursor, bool)
                        assert self.ledger.cursor >= result_cursor
                    return response, events

    def await_output(self, terminal_id: str, marker: str, *, after_cursor: int) -> NativeEnvelope:
        deadline = time.monotonic() + TIMEOUT
        while True:
            matched = self.ledger.output_after(after_cursor, terminal_id, marker)
            if matched is not None:
                return matched
            _ = self._read(deadline)

    def receive_event(self, event_type: str, terminal_id: str) -> NativeEnvelope:
        assert self.client is not None
        deadline = time.monotonic() + TIMEOUT
        while True:
            message = self._read(deadline)
            payload = message.body.get("payload")
            if (
                message.kind == "event"
                and message.body.get("type") == event_type
                and isinstance(payload, dict)
                and payload.get("terminal_id") == terminal_id
            ):
                return message

    def create(self, command_id: str) -> tuple[Mapping[str, JSONValue], list[NativeEnvelope]]:
        receipt, events = self.request(
            "terminal.create",
            command_id,
            {"actor_kind": "native_human", "cwd": str(self.root)},
        )
        result = receipt_result(receipt)
        terminal_id = str(result["terminal_id"])
        opened_cursor = next(
            event.body["cursor"]
            for event in events
            if event.body.get("type") == "terminal.opened"
        )
        assert isinstance(opened_cursor, int) and not isinstance(opened_cursor, bool)
        _ = await_prompt_terminator(self, terminal_id, "", after_cursor=opened_cursor, timeout=TIMEOUT)
        return result, events

    def close(self) -> None:
        self.terminal.close_all()
        self.disconnect()
        assert self.terminal.active_process_ids == ()

    def _read(self, deadline: float) -> NativeEnvelope:
        assert self.client is not None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("native bridge read deadline expired")
            self.client.settimeout(remaining)
            message = receive_frame(self.client)
            if message.kind == "ping":
                self._pong(self.client, message)
                continue
            if message.kind == "event":
                self.ledger.record(message)
            return message

    def _pong(self, client: socket.socket, ping: NativeEnvelope) -> None:
        pong = envelope("pong", frame_id=f"pong-{ping.id}", in_reply_to=ping.id,
                        body={**ping.body, "session_capability": self.token})
        client.sendall(encode_frame(pong))


def receipt_result(receipt: NativeEnvelope) -> Mapping[str, JSONValue]:
    assert receipt.kind == "receipt", receipt.body
    value = receipt.body.get("result")
    assert isinstance(value, dict)
    return value


def event_payloads(events: list[NativeEnvelope], event_type: str) -> list[Mapping[str, JSONValue]]:
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
