from __future__ import annotations

import json
import socket
import threading
from pathlib import Path
from typing import cast

from birkin.native.capability import BootstrapSecretStore
from birkin.native.endpoint import NativeBridgeEndpoint
from birkin.native.protocol import encode_frame
from birkin.native.server import NativeBridgeServer
from birkin.native.transport import receive_frame
from birkin.workspace import WorkspaceService
from tests.native_bridge_support import envelope, hello


def _serve_once(endpoint: NativeBridgeEndpoint) -> threading.Thread:
    thread = threading.Thread(target=endpoint.serve_once, daemon=True)
    thread.start()
    return thread


def _runtime(
    tmp_path: Path,
) -> tuple[NativeBridgeEndpoint, BootstrapSecretStore]:
    source = WorkspaceService(
        root=tmp_path / "workspace",
        session_id="session-1",
        handlers={},
    )
    capabilities = BootstrapSecretStore(tmp_path / "native")
    bridge = NativeBridgeServer(
        source,
        capabilities=capabilities,
        instance_id="instance-1",
        server_version="1.0.0",
    )
    endpoint = NativeBridgeEndpoint.loopback(
        bridge,
        capabilities=capabilities,
        instance_id="instance-1",
        server_version="1.0.0",
    )
    return endpoint, capabilities


def test_loopback_endpoint_record_contains_connect_metadata(
    tmp_path: Path,
) -> None:
    endpoint, capabilities = _runtime(tmp_path)
    try:
        record = cast(
            dict[str, object],
            json.loads(capabilities.endpoint_path.read_text("utf-8")),
        )

        assert record["transport"] == "loopback"
        assert record["host"] == "127.0.0.1"
        assert record["port"] == endpoint.address[1]
        assert record["instance_id"] == "instance-1"
        assert record["server_version"] == "1.0.0"
        assert record["protocol_versions"] == [1]
    finally:
        endpoint.close()


def test_loopback_endpoint_serves_real_authenticated_connection(
    tmp_path: Path,
) -> None:
    endpoint, capabilities = _runtime(tmp_path)
    errors: list[BaseException] = []

    def serve() -> None:
        try:
            endpoint.serve_once()
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    client = socket.create_connection(endpoint.address, timeout=1)
    try:
        bootstrap = capabilities.current()
        client.sendall(
            encode_frame(hello(bootstrap_secret=bootstrap.secret))
        )
        ready = receive_frame(client)
        rotated = cast(
            dict[str, object],
            json.loads(capabilities.endpoint_path.read_text("utf-8")),
        )

        assert ready.kind == "ready"
        assert ready.body["transport"] == "loopback"
        assert rotated["host"] == "127.0.0.1"
        assert rotated["port"] == endpoint.address[1]
    finally:
        client.close()
        thread.join(timeout=2)
        endpoint.close()
    assert errors == []
    assert capabilities.endpoint_path.exists() is False


def test_loopback_non_ascii_bootstrap_returns_typed_error_and_bridge_survives(
    tmp_path: Path,
) -> None:
    endpoint, capabilities = _runtime(tmp_path)
    invalid_secret = "non-ascii-é"
    first_thread = _serve_once(endpoint)
    first_client = socket.create_connection(endpoint.address, timeout=1)
    try:
        first_client.sendall(
            encode_frame(hello(bootstrap_secret=invalid_secret))
        )
        error = receive_frame(first_client)

        assert error.kind == "error"
        assert error.in_reply_to is None
        assert error.body["code"] == "E_BOOTSTRAP_INVALID"
        assert error.body["retryable"] is False
        assert set(error.body) == {"code", "message", "retryable"}
        assert invalid_secret not in str(error.to_dict())
    finally:
        first_client.close()
        first_thread.join(timeout=2)

    second_thread = _serve_once(endpoint)
    second_client = socket.create_connection(endpoint.address, timeout=1)
    try:
        valid_secret = capabilities.current().secret
        second_client.sendall(encode_frame(hello(bootstrap_secret=valid_secret)))
        ready = receive_frame(second_client)

        assert ready.kind == "ready"
        assert ready.body["transport"] == "loopback"
    finally:
        second_client.close()
        second_thread.join(timeout=2)
        endpoint.close()


def test_loopback_non_ascii_capability_returns_typed_error_and_bridge_survives(
    tmp_path: Path,
) -> None:
    endpoint, capabilities = _runtime(tmp_path)
    first_thread = _serve_once(endpoint)
    first_client = socket.create_connection(endpoint.address, timeout=1)
    try:
        first_client.sendall(
            encode_frame(hello(bootstrap_secret=capabilities.current().secret))
        )
        ready = receive_frame(first_client)
        capability = ready.body["capability"]
        assert isinstance(capability, dict)
        token = capability["token"]
        assert isinstance(token, str)
        invalid_token = "non-ascii-é"
        first_client.sendall(encode_frame(envelope(
            "ping",
            frame_id="invalid-capability",
            body={
                "session_capability": invalid_token,
                "sent_at": "2026-08-21T00:00:00Z",
            },
        )))
        error = receive_frame(first_client)

        assert error.kind == "error"
        assert error.in_reply_to is None
        assert error.body["code"] == "E_CAPABILITY_INVALID"
        assert error.body["retryable"] is False
        assert set(error.body) == {"code", "message", "retryable"}
        assert invalid_token not in str(error.to_dict())
        assert token not in str(error.to_dict())
    finally:
        first_client.close()
        first_thread.join(timeout=2)

    second_thread = _serve_once(endpoint)
    second_client = socket.create_connection(endpoint.address, timeout=1)
    try:
        second_client.sendall(
            encode_frame(hello(bootstrap_secret=capabilities.current().secret))
        )
        ready = receive_frame(second_client)

        assert ready.kind == "ready"
        assert ready.body["transport"] == "loopback"
    finally:
        second_client.close()
        second_thread.join(timeout=2)
        endpoint.close()
