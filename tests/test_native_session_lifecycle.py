from __future__ import annotations

import socket
from collections.abc import Callable, Mapping
from pathlib import Path
from threading import Thread
from typing import cast

import pytest

from birkin import config
from birkin.native.capability import BootstrapSecretStore
from birkin.native.protocol import NativeEnvelope, encode_frame
from birkin.native.server import NativeBridgeServer
from birkin.native.transport import receive_frame
from birkin.workspace import WorkspaceCommand, WorkspaceEvent, WorkspaceHub
from birkin.workspace.service import CommandHandler
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
    def handlers(
        session_id: str,
        emit: Callable[[str, dict[str, object]], WorkspaceEvent],
    ) -> Mapping[str, CommandHandler]:
        failed_text: str | None = None
        active_run = True

        def compact(_payload: dict[str, object]) -> dict[str, object]:
            _ = emit(
                "session.compacted",
                {"session_id": session_id, "compacted": True},
            )
            return {"compacted": True}

        def chat(payload: dict[str, object]) -> dict[str, object]:
            nonlocal failed_text
            text = str(payload["text"])
            if text == "fail once" and failed_text is None:
                failed_text = text
                raise RuntimeError("intent failed")
            return {"reply": text}

        def steer(payload: dict[str, object]) -> dict[str, object]:
            if not active_run:
                raise RuntimeError("no active run")
            text = str(payload["text"])
            _ = emit("turn.steered", {"text": text})
            return {"steered": True}

        def retry(_payload: dict[str, object]) -> dict[str, object]:
            if failed_text is None:
                raise RuntimeError("no failed intent to retry")
            _ = emit("message.user", {"text": failed_text})
            return {"reply": failed_text}

        return {
            "chat.send": chat,
            "chat.steer": steer,
            "chat.retry": retry,
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
) -> tuple[socket.socket, str, Thread, list[BaseException]]:
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
    payload: Mapping[str, object],
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
                        "payload": dict(payload),
                        "client_context": {"surface": "macos", "view_id": "main"},
                    },
                },
            )
        )
    )


def _receive_event_type(
    client: socket.socket,
    event_type: str,
) -> NativeEnvelope:
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    payloads: dict[str, dict[str, object]] = {
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
        client.sendall(
            encode_frame(
                envelope(
                    "subscribe",
                    frame_id="subscribe-second",
                    body={
                        "session_id": "second",
                        "after_cursor": 0,
                        "known_instance_id": None,
                        "session_capability": token,
                        "surfaces": {},
                    },
                )
            )
        )
        assert receive_kind(client, "snapshot").body["session_id"] == "second"
    finally:
        client.close()
        thread.join(timeout=2)  # type: ignore[union-attr]
        hub.close()
    assert errors == []


def test_chat_steer_over_socket_emits_real_event_receipt(
    tmp_path: Path,
) -> None:
    bridge, hub = _server(tmp_path)
    server_socket, client = socket.socketpair()
    thread, errors = serve(
        bridge, server_socket, transport="uds", peer_uid=local_peer_uid()
    )
    try:
        token = handshake(client)
        _send(client, token, "chat.steer", "steer-1", 0, {"text": "check tests"})
        receipt = receive_kind(client, "receipt")
        event = next(event for event in hub.events() if event.type == "turn.steered")

        assert receipt.body["state"] == "completed"
        assert receipt.body["command_id"] == "steer-1"
        assert event.command_id == "steer-1"
        assert event.payload == {"text": "check tests"}
    finally:
        client.close()
        thread.join(timeout=2)
        hub.close()
    assert errors == []


def test_chat_retry_over_socket_creates_new_intent_and_preserves_failure(
    tmp_path: Path,
) -> None:
    bridge, hub = _server(tmp_path)
    server_socket, client = socket.socketpair()
    thread, errors = serve(
        bridge, server_socket, transport="uds", peer_uid=local_peer_uid()
    )
    failed_command = WorkspaceCommand.parse({
        "protocol_version": 1,
        "command_id": "failed-intent",
        "expected_cursor": 0,
        "type": "chat.send",
        "payload": {"text": "fail once"},
        "client_context": {"surface": "test", "view_id": "setup"},
    })
    with pytest.raises(RuntimeError, match="intent failed"):
        _ = hub.submit(failed_command, actor_id="test:setup")
    try:
        token = handshake(client)
        failed = next(event for event in hub.events() if event.type == "command.failed")
        assert failed.command_id == "failed-intent"

        _send(client, token, "chat.retry", "retry-intent", hub.snapshot().cursor, {})
        receipt = receive_kind(client, "receipt")
        retried = next(event for event in hub.events() if event.type == "message.user")

        assert receipt.body["state"] == "completed"
        assert receipt.body["command_id"] == "retry-intent"
        assert retried.command_id == "retry-intent"
        assert retried.payload == {"text": "fail once"}
        assert any(
            event.type == "command.failed" and event.command_id == "failed-intent"
            for event in hub.events()
        )
    finally:
        client.close()
        thread.join(timeout=2)
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
        payload = cast(dict[str, object], event.body["payload"])
        assert payload["compacted"] is True
    finally:
        client.close()
        thread.join(timeout=2)  # type: ignore[union-attr]
        hub.close()
    assert errors == []


def test_config_set_over_socket_emits_requested_and_effective_or_typed_rejection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        rejected_payload = cast(dict[str, object], rejected.body["payload"])
        assert "invalid config" in str(rejected_payload["reason"])
        assert config.load_config()["max_turns"] == 12
    finally:
        client.close()
        thread.join(timeout=2)  # type: ignore[union-attr]
        hub.close()
    assert errors == []


def test_working_memory_merge_clear_and_typed_errors_over_socket(
    tmp_path: Path,
) -> None:
    bridge, hub = _server(tmp_path)
    client, token, thread, errors = _connect(bridge)
    try:
        _send(
            client,
            token,
            "memory.write",
            "memory-merge",
            0,
            {
                "op": "merge",
                "expected_revision": 0,
                "fields": {"constraints": ["Offline", "Offline"]},
            },
        )
        merge_receipt = receive_kind(client, "receipt")
        requested = _receive_event_type(client, "working_memory.requested")
        updated = _receive_event_type(client, "working_memory.updated")
        requested_payload = cast(dict[str, object], requested.body["payload"])
        effective = cast(dict[str, object], requested_payload["effective"])
        assert merge_receipt.body["state"] == "completed"
        assert effective["constraints"] == ["Offline"]
        assert cast(dict[str, object], updated.body["payload"])["working_memory"] == effective

        _send(
            client,
            token,
            "memory.write",
            "memory-clear",
            hub.snapshot().cursor,
            {"op": "clear", "expected_revision": 1},
        )
        clear_receipt = receive_kind(client, "receipt")
        _ = _receive_event_type(client, "working_memory.requested")
        cleared = _receive_event_type(client, "working_memory.updated")
        clear_state = cast(
            dict[str, object],
            cast(dict[str, object], cleared.body["payload"])["working_memory"],
        )
        assert clear_receipt.body["state"] == "completed"
        assert clear_state["revision"] == 2

        _send(
            client,
            token,
            "memory.write",
            "memory-stale",
            hub.snapshot().cursor,
            {"op": "clear", "expected_revision": 1},
        )
        stale = receive_kind(client, "error")
        assert stale.body["code"] == "E_WORKING_MEMORY_REVISION"
        assert stale.body["current_revision"] == 2
        assert "Traceback" not in str(stale.body)

        _send(
            client,
            token,
            "memory.write",
            "memory-budget",
            hub.snapshot().cursor,
            {
                "op": "merge",
                "expected_revision": 2,
                "fields": {
                    "evidence": [
                        f"{index}:" + "x" * 1992 for index in range(11)
                    ]
                },
            },
        )
        budget = receive_kind(client, "error")
        assert budget.body["code"] == "E_WORKING_MEMORY_BUDGET"
        assert budget.body["limit"] == 20_000
        assert "Traceback" not in str(budget.body)
        assert len(str(budget.body)) < 600
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
        payload = cast(dict[str, object], event.body["payload"])
        assert payload["name"] == "Native plan"
        assert hub.summaries()[0]["name"] == "Native plan"
    finally:
        client.close()
        thread.join(timeout=2)  # type: ignore[union-attr]
        hub.close()
    assert errors == []
