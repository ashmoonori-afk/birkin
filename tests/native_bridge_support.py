from __future__ import annotations

import os
import socket
import threading
from pathlib import Path
from typing import final

from birkin.native.capability import BootstrapSecretStore
from birkin.native.protocol import (
    NATIVE_PROTOCOL_NAME,
    NATIVE_PROTOCOL_VERSION,
    NativeEnvelope,
    NativeProtocolError,
    encode_frame,
)
from birkin.native.server import NativeBridgeServer
from birkin.native.transport import NativeConnection, receive_frame
from birkin.workspace import WorkspaceService


def local_peer_uid() -> int:
    geteuid = getattr(os, "geteuid", None)
    if not callable(geteuid):
        return 0
    value = geteuid()
    return value if isinstance(value, int) else 0


def envelope(
    kind: str,
    *,
    frame_id: str,
    body: dict[str, object],
    in_reply_to: str | None = None,
) -> NativeEnvelope:
    return NativeEnvelope.parse(
        {
            "protocol": NATIVE_PROTOCOL_NAME,
            "protocol_version": NATIVE_PROTOCOL_VERSION,
            "kind": kind,
            "id": frame_id,
            "in_reply_to": in_reply_to,
            "body": body,
        }
    )


def hello(
    *,
    bootstrap_secret: str | None,
    surface: str = "macos",
    view_id: str = "main",
) -> NativeEnvelope:
    return envelope(
        "hello",
        frame_id="hello-1",
        body={
            "client": "birkin-macos",
            "client_version": "1.0.0",
            "client_build": "100",
            "supported_protocol_versions": [NATIVE_PROTOCOL_VERSION],
            "surface": surface,
            "view_id": view_id,
            "bootstrap_secret": bootstrap_secret,
        },
    )


def server(
    tmp_path: Path,
) -> tuple[NativeBridgeServer, BootstrapSecretStore]:
    bridge, capabilities, _source = server_with_source(tmp_path)
    return bridge, capabilities


def server_with_source(
    tmp_path: Path,
) -> tuple[NativeBridgeServer, BootstrapSecretStore, WorkspaceService]:
    source = WorkspaceService(
        root=tmp_path / "workspace",
        session_id="session-1",
        handlers={"chat.send": lambda payload: {"reply": str(payload["text"])}},
    )
    capabilities = BootstrapSecretStore(tmp_path / "native")
    bridge = NativeBridgeServer(
        source,
        capabilities=capabilities,
        instance_id="instance-1",
        server_version="1.0.0",
    )
    return bridge, capabilities, source


def serve(
    bridge: NativeBridgeServer,
    connection: socket.socket,
    *,
    transport: str,
    peer_uid: int | None,
) -> tuple[threading.Thread, list[BaseException]]:
    errors: list[BaseException] = []

    def run() -> None:
        try:
            bridge.serve_connection(
                NativeConnection(connection, peer_uid),
                transport=transport,
            )
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, errors


def handshake(
    client: socket.socket,
    *,
    surface: str = "macos",
    view_id: str = "main",
) -> str:
    client.sendall(
        encode_frame(
            hello(
                bootstrap_secret=None,
                surface=surface,
                view_id=view_id,
            )
        )
    )
    ready = receive_frame(client)
    capability = ready.body["capability"]
    assert isinstance(capability, dict)
    token = capability["token"]
    assert isinstance(token, str)
    client.sendall(
        encode_frame(
            envelope(
                "subscribe",
                frame_id="subscribe-1",
                body={
                    "session_id": "session-1",
                    "after_cursor": 0,
                    "known_instance_id": None,
                    "session_capability": token,
                    "surfaces": {},
                },
            )
        )
    )
    _ = receive_kind(client, "snapshot")
    return token


def receive_kind(
    client: socket.socket,
    kind: str,
) -> NativeEnvelope:
    for _index in range(16):
        envelope = receive_frame(client)
        if envelope.kind == kind:
            return envelope
    raise AssertionError(f"did not receive {kind}")


@final
class CorrelatedFrameReader:
    """Continuously service heartbeats and signal complete correlated frames."""

    def __init__(self, client: socket.socket, token: str) -> None:
        self._client = client
        self._token = token
        self._lock = threading.Lock()
        self._expected: dict[str, threading.Event] = {}
        self._frames: dict[str, NativeEnvelope] = {}
        self._stopping = threading.Event()
        self._failure: NativeProtocolError | OSError | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def expect(self, request_id: str) -> None:
        with self._lock:
            self._expected[request_id] = threading.Event()

    def receive(self, request_id: str, *, timeout: float = 2) -> NativeEnvelope:
        with self._lock:
            ready = self._expected[request_id]
        assert ready.wait(timeout=timeout)
        if self._failure is not None:
            raise self._failure
        with self._lock:
            return self._frames.pop(request_id)

    def close(self) -> None:
        self._stopping.set()
        try:
            self._client.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._client.close()
        self._thread.join(timeout=2)
        assert not self._thread.is_alive()
        if self._failure is not None:
            raise self._failure

    def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                frame = receive_frame(self._client)
                if frame.kind == "ping":
                    self._client.sendall(encode_frame(envelope(
                        "pong",
                        frame_id=f"pong-{frame.id}",
                        in_reply_to=frame.id,
                        body={**frame.body, "session_capability": self._token},
                    )))
                    continue
            except (NativeProtocolError, OSError) as exc:
                if not self._stopping.is_set():
                    self._failure = exc
                    with self._lock:
                        for expected in self._expected.values():
                            expected.set()
                return
            if frame.in_reply_to is not None:
                with self._lock:
                    self._frames[frame.in_reply_to] = frame
                    expected = self._expected.get(frame.in_reply_to)
                    if expected is not None:
                        expected.set()


def command_body(
    token: str,
    *,
    command_id: str,
    cursor: int,
    text: str,
) -> dict[str, object]:
    return {
        "session_capability": token,
        "command": {
            "protocol_version": 1,
            "command_id": command_id,
            "expected_cursor": cursor,
            "type": "chat.send",
            "payload": {"text": text},
            "client_context": {"surface": "macos", "view_id": "main"},
        },
    }
