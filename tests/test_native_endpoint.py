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
from tests.native_bridge_support import hello


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
