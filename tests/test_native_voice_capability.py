from __future__ import annotations

import socket
from pathlib import Path
from typing import cast

import pytest

from birkin.native.capability import BootstrapSecretStore
from birkin.native.protocol import encode_frame
from birkin.native.server import NativeBridgeServer
from birkin.native.transport import receive_frame
from birkin.workspace import WorkspaceService
from tests.native_bridge_support import hello, local_peer_uid, serve


@pytest.mark.parametrize("available", [False, True])
def test_ready_advertises_python_voice_input_health_only(
    tmp_path: Path,
    available: bool,
) -> None:
    workspace = WorkspaceService(
        root=tmp_path / "workspace",
        session_id="session-1",
        handlers={"chat.send": lambda payload: payload},
    )
    bridge = NativeBridgeServer(
        workspace,
        capabilities=BootstrapSecretStore(tmp_path / "native"),
        instance_id="instance-voice",
        server_version="1.0.0",
        voice_input_available=available,
    )
    server_socket, client = socket.socketpair()
    thread, errors = serve(
        bridge, server_socket, transport="uds", peer_uid=local_peer_uid()
    )
    try:
        client.sendall(encode_frame(hello(bootstrap_secret=None)))
        ready = receive_frame(client)
        capabilities = cast(dict[str, object], ready.body["capabilities"])
        features = cast(dict[str, object], capabilities["features"])
        assert features["voice_input"] is available
    finally:
        client.close()
        thread.join(timeout=2)
    assert errors == []
