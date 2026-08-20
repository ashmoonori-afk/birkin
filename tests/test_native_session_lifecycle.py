from __future__ import annotations

import socket
from pathlib import Path

from birkin import config
from birkin.native.capability import BootstrapSecretStore
from birkin.native.protocol import encode_frame
from birkin.native.server import NativeBridgeServer
from birkin.native.transport import receive_frame
from birkin.workspace import WorkspaceHub
from tests.native_bridge_support import (
    envelope,
    handshake,
    hello,
    local_peer_uid,
    receive_kind,
    serve,
    server_with_source,
)


def _server(tmp_path: Path) -> tuple[NativeBridgeServer, WorkspaceHub]:
    def handlers(session_id: str, emit):  # type: ignore[no-untyped-def]
        def compact(_payload: dict[str, object]) -> dict[str, object]:
            _ = emit(
                "session.compacted",
                {"session_id": session_id, "compacted": True},
            )
            return {"compacted": True}

        return {
            "chat.send": lambda payload: {"reply": payload["text"]},
            "session.compact": compact,
        }

    hub = WorkspaceHub(
        root=tmp_path / "workspace",
        handler_factory=handlers,
        config_setter=config.set_config,
    )
    session, _ = hub.create("session-1")
    bridge = NativeBridgeServer(
        session.service,
        session_authority=hub,
        config_authority=hub,
        capabilities=BootstrapSecretStore(tmp_path / "native"),
        instance_id="instance-1",
        server_version="1.0.0",
    )
    return bridge, hub


def _connect(
    bridge: NativeBridgeServer,
) -> tuple[socket.socket, str, object, list[BaseException]]:
    server_socket, client = socket.socketpair()
    thread, errors = serve(
        bridge,
        server_socket,
        transport="uds",
        peer_uid=local_peer_uid(),
    )
    client.sendall(encode_frame(hello(bootstrap_secret=None)))
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
    assert receive_kind(client, "snapshot").kind == "snapshot"
    return client, token, thread, errors


def _send(
    client: socket.socket,
    token: str,
    command_type: str,
    command_id: str,
    cursor: int,
    payload: dict[str, object],
) -> None:
    client.sendall(
        encode_frame(
            envelope(
                "command",
                frame_id=command_id,
                body={
                    "session_capability": token,
                    "command": {
                        "protocol_version": 1,
                        "command_id": command_id,
                        "expected_cursor": cursor,
                        "type": command_type,
                        "payload": payload,
                        "client_context": {"surface": "macos", "view_id": "main"},
                    },
                },
            )
        )
    )


def _receive_event_type(client: socket.socket, event_type: str):  # type: ignore[no-untyped-def]
    for _ in range(8):
        event = receive_kind(client, "event")
        if event.body["type"] == event_type:
            return event
    raise AssertionError(f"did not receive event {event_type}")


def _advertised_commands(bridge: NativeBridgeServer) -> set[str]:
    server_socket, client = socket.socketpair()
    thread, errors = serve(
        bridge,
        server_socket,
        transport="uds",
        peer_uid=local_peer_uid(),
    )
    try:
        client.sendall(encode_frame(hello(bootstrap_secret=None)))
        ready = receive_frame(client)
        capabilities = ready.body["capabilities"]
        assert isinstance(capabilities, dict)
        commands = capabilities["commands"]
        assert isinstance(commands, list)
        return {str(command) for command in commands}
    finally:
        client.close()
        thread.join(timeout=2)
        assert errors == []


def test_advertised_handlers_equal_wired_authority_in_both_configurations(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    legacy, _capabilities, source = server_with_source(tmp_path / "legacy")
    assert _advertised_commands(legacy) == set(source.supported_commands)

    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    enhanced, hub = _server(tmp_path / "enhanced")
    try:
        assert _advertised_commands(enhanced) == set(hub.supported_commands)
    finally:
        hub.close()


def test_unwired_lifecycle_and_config_commands_are_journaled_refusals(
    tmp_path: Path,
) -> None:
    payloads = {
        "session.create": {"session_id": "second"},
        "session.select": {"session_id": "second"},
        "session.rename": {"session_id": "session-1", "name": "Plan"},
        "session.compact": {},
        "config.set": {"key": "max_turns", "value": 12},
    }
    for index, (command_type, payload) in enumerate(payloads.items()):
        bridge, _capabilities, source = server_with_source(tmp_path / str(index))
        server_socket, client = socket.socketpair()
        thread, errors = serve(
            bridge,
            server_socket,
            transport="uds",
            peer_uid=local_peer_uid(),
        )
        try:
            token = handshake(client)
            _send(client, token, command_type, f"unsupported-{index}", 0, payload)
            error = receive_kind(client, "error")
            assert error.body["code"] == "E_UNSUPPORTED_COMMAND"
            assert source.events()[-1].type == "command.failed"
        finally:
            client.close()
            thread.join(timeout=2)
        assert errors == []


def test_session_create_over_socket_emits_event_and_updates_projection(
    tmp_path: Path,
) -> None:
    bridge, hub = _server(tmp_path)
    client, token, thread, errors = _connect(bridge)
    try:
        _send(client, token, "session.create", "create-1", 0, {"session_id": "second"})
        receipt = receive_kind(client, "receipt")
        event = _receive_event_type(client, "session.created")

        assert receipt.body["state"] == "completed"
        assert event.body["type"] == "session.created"
        assert hub.get("second") is not None
        assert hub.snapshot().cursor == 4
    finally:
        client.close()
        thread.join(timeout=2)  # type: ignore[union-attr]
        hub.close()
    assert errors == []


def test_session_select_over_socket_emits_event_and_changes_projection(
    tmp_path: Path,
) -> None:
    bridge, hub = _server(tmp_path)
    _second, _ = hub.create("second")
    client, token, thread, errors = _connect(bridge)
    try:
        _send(client, token, "session.select", "select-1", 0, {"session_id": "second"})
        receipt = receive_kind(client, "receipt")
        event = _receive_event_type(client, "session.selected")

        assert receipt.body["state"] == "completed"
        assert event.body["payload"] == {"session_id": "second"}
        assert hub.snapshot().session_id == "second"
    finally:
        client.close()
        thread.join(timeout=2)  # type: ignore[union-attr]
        hub.close()
    assert errors == []


def test_session_compact_over_socket_returns_canonical_receipt(
    tmp_path: Path,
) -> None:
    bridge, hub = _server(tmp_path)
    client, token, thread, errors = _connect(bridge)
    try:
        _send(client, token, "session.compact", "compact-1", 0, {})
        receipt = receive_kind(client, "receipt")
        event = _receive_event_type(client, "session.compacted")

        assert receipt.body["state"] == "completed"
        assert receipt.body["result_event_cursor"] == 4
        assert event.body["payload"]["compacted"] is True
    finally:
        client.close()
        thread.join(timeout=2)  # type: ignore[union-attr]
        hub.close()
    assert errors == []


def test_config_set_over_socket_emits_requested_and_effective_or_typed_rejection(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    bridge, hub = _server(tmp_path)
    client, token, thread, errors = _connect(bridge)
    try:
        _send(client, token, "config.set", "config-valid", 0, {"key": "max_turns", "value": 12})
        receipt = receive_kind(client, "receipt")
        requested = _receive_event_type(client, "settings.requested")
        effective = _receive_event_type(client, "settings.updated")

        assert receipt.body["state"] == "completed"
        assert requested.body["payload"] == {"key": "max_turns", "value": 12}
        assert effective.body["payload"] == {"key": "max_turns", "value": 12}
        assert config.load_config()["max_turns"] == 12

        _send(
            client,
            token,
            "config.set",
            "config-invalid",
            hub.snapshot().cursor,
            {"key": "max_turns", "value": "many"},
        )
        error = receive_kind(client, "error")
        rejected = _receive_event_type(client, "settings.rejected")

        assert error.body["code"] == "E_CONFIG_REJECTED"
        assert "invalid config" in str(error.body["message"])
        assert "Traceback" not in str(error.body)
        assert len(str(error.body)) < 600
        assert "invalid config" in str(rejected.body["payload"]["reason"])
        assert config.load_config()["max_turns"] == 12
    finally:
        client.close()
        thread.join(timeout=2)  # type: ignore[union-attr]
        hub.close()
    assert errors == []


def test_session_rename_over_socket_updates_canonical_summary(
    tmp_path: Path,
) -> None:
    bridge, hub = _server(tmp_path)
    client, token, thread, errors = _connect(bridge)
    try:
        _send(
            client,
            token,
            "session.rename",
            "rename-1",
            0,
            {"session_id": "session-1", "name": "Native plan"},
        )
        receipt = receive_kind(client, "receipt")
        event = _receive_event_type(client, "session.renamed")

        assert receipt.body["state"] == "completed"
        assert event.body["payload"]["name"] == "Native plan"
        assert hub.summaries()[0]["name"] == "Native plan"
    finally:
        client.close()
        thread.join(timeout=2)  # type: ignore[union-attr]
        hub.close()
    assert errors == []
