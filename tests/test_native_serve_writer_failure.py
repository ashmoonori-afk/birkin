from __future__ import annotations

import socket
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import final

import pytest

from birkin.native.capability import BootstrapSecretStore
from birkin.native.protocol import NativeEnvelope, NativeProtocolError, encode_frame
from birkin.native.server import NativeBridgeServer
from birkin.native.transport import NativeConnection
from birkin.workspace import WorkspaceCommand, WorkspaceService
from birkin.workspace.contracts import JsonValue
from tests.native_bridge_support import envelope, handshake, local_peer_uid, serve


@final
@dataclass(frozen=True, slots=True)
class _WriterFailureHarness:
    client: socket.socket
    server_thread: threading.Thread
    errors: list[BaseException]
    capabilities: BootstrapSecretStore
    send_entered: threading.Event
    release_writer: threading.Event
    interrupt_observed: threading.Event
    cleanup_completed: threading.Event
    cleanup_calls: list[str]
    writer_threads: list[threading.Thread]


def _command() -> WorkspaceCommand:
    return WorkspaceCommand.parse(
        {
            "protocol_version": 1,
            "command_id": "block-native-writer",
            "expected_cursor": 0,
            "type": "chat.send",
            "payload": {"text": "trigger writer"},
            "client_context": {"surface": "macos", "view_id": "main"},
        }
    )


def _writer_failure_harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_error_response: bool,
) -> _WriterFailureHarness:
    send_entered = threading.Event()
    release_writer = threading.Event()
    interrupt_observed = threading.Event()
    cleanup_completed = threading.Event()
    cleanup_calls: list[str] = []
    writer_threads: list[threading.Thread] = []

    def chat(payload: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return {"reply": str(payload["text"])}

    def cleanup() -> None:
        cleanup_calls.append("cleanup")
        cleanup_completed.set()

    source = WorkspaceService(
        root=tmp_path / "workspace",
        session_id="session-1",
        handlers={"chat.send": chat},
    )
    capabilities = BootstrapSecretStore(tmp_path / "native")
    bridge = NativeBridgeServer(
        source,
        capabilities=capabilities,
        instance_id="instance-1",
        server_version="1.0.0",
        on_disconnect=cleanup,
    )
    original_send = NativeConnection.send

    def block_writer(
        connection: NativeConnection,
        message: NativeEnvelope,
    ) -> None:
        if threading.current_thread().name == "birkin-native-writer":
            if not writer_threads:
                writer_threads.append(threading.current_thread())
            send_entered.set()
            assert release_writer.wait(timeout=15)
            return
        if fail_error_response and message.kind == "error":
            raise NativeProtocolError(
                "E_SEND_TIMEOUT",
                "injected protocol response failure",
            )
        original_send(connection, message)

    def refuse_interrupt(_connection: NativeConnection) -> None:
        interrupt_observed.set()

    monkeypatch.setattr(NativeConnection, "send", block_writer)
    monkeypatch.setattr(NativeConnection, "interrupt", refuse_interrupt)
    server_socket, client = socket.socketpair()
    client.settimeout(2)
    server_thread, errors = serve(
        bridge,
        server_socket,
        transport="uds",
        peer_uid=local_peer_uid(),
    )
    _ = handshake(client)
    _ = source.submit(_command(), actor_id="test:writer-failure")
    assert send_entered.wait(timeout=5)
    return _WriterFailureHarness(
        client=client,
        server_thread=server_thread,
        errors=errors,
        capabilities=capabilities,
        send_entered=send_entered,
        release_writer=release_writer,
        interrupt_observed=interrupt_observed,
        cleanup_completed=cleanup_completed,
        cleanup_calls=cleanup_calls,
        writer_threads=writer_threads,
    )


def _release_writer(harness: _WriterFailureHarness) -> None:
    harness.release_writer.set()
    for writer in harness.writer_threads:
        writer.join(timeout=2)
    harness.client.close()
    harness.server_thread.join(timeout=2)


def test_serve_connection_reports_writer_that_survives_interrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    harness = _writer_failure_harness(
        tmp_path,
        monkeypatch,
        fail_error_response=False,
    )

    # When
    try:
        harness.client.close()
        harness.server_thread.join(timeout=10)
        server_alive = harness.server_thread.is_alive()
        errors = tuple(harness.errors)
        cleanup_observed = harness.cleanup_completed.wait(timeout=2)
        writer_alive_before_release = [
            writer.is_alive() for writer in harness.writer_threads
        ]
    finally:
        _release_writer(harness)

    # Then
    assert not server_alive
    assert cleanup_observed
    assert harness.cleanup_calls == ["cleanup"]
    assert harness.interrupt_observed.is_set()
    assert harness.capabilities.active_session_count() == 0
    assert writer_alive_before_release == [True]
    assert len(errors) == 1
    failure = errors[0]
    assert isinstance(failure, TimeoutError)
    assert str(failure) == (
        "native writer did not terminate after connection interrupt"
    )
    assert not any(writer.is_alive() for writer in harness.writer_threads)


def test_writer_failure_is_chained_without_masking_protocol_send_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    harness = _writer_failure_harness(
        tmp_path,
        monkeypatch,
        fail_error_response=True,
    )

    # When
    try:
        harness.client.sendall(encode_frame(envelope(
            "ping",
            frame_id="invalid-capability",
            body={
                "session_capability": "wrong",
                "sent_at": "2026-09-01T00:00:00Z",
            },
        )))
        harness.server_thread.join(timeout=10)
        errors = tuple(harness.errors)
        cleanup_observed = harness.cleanup_completed.wait(timeout=2)
    finally:
        _release_writer(harness)

    # Then
    assert cleanup_observed
    assert harness.cleanup_calls == ["cleanup"]
    assert harness.interrupt_observed.is_set()
    assert harness.capabilities.active_session_count() == 0
    assert len(errors) == 1
    primary = errors[0]
    assert isinstance(primary, NativeProtocolError)
    assert primary.code == "E_SEND_TIMEOUT"
    writer_failure = primary.__cause__
    assert isinstance(writer_failure, TimeoutError)
    assert str(writer_failure) == (
        "native writer did not terminate after connection interrupt"
    )
    assert not any(writer.is_alive() for writer in harness.writer_threads)
