from __future__ import annotations

import socket
from pathlib import Path

from birkin.native.protocol import encode_frame
from birkin.native.transport import receive_frame
from birkin.workspace import SESSION_PRESETS, WorkspaceService
from tests.native_bridge_support import hello, local_peer_uid, serve, server


EXPECTED_PRESETS = [
    {
        "id": "research",
        "name": "Research",
        "prefill": "Research the following topic:\n",
        "persistent": False,
        "order": 0,
    },
    {
        "id": "data-analysis",
        "name": "Data Analysis",
        "prefill": "Analyze the following data:\n",
        "persistent": False,
        "order": 1,
    },
    {
        "id": "writing",
        "name": "Writing",
        "prefill": "Help me write:\n",
        "persistent": False,
        "order": 2,
    },
    {
        "id": "automation",
        "name": "Automation",
        "prefill": "Automate the following workflow:\n",
        "persistent": False,
        "order": 3,
    },
]


def test_workspace_defines_four_ordered_data_only_session_presets(
    tmp_path: Path,
) -> None:
    service = WorkspaceService(
        root=tmp_path,
        session_id="session-1",
        handlers={},
    )

    assert [preset.to_json() for preset in SESSION_PRESETS] == EXPECTED_PRESETS
    assert [preset.to_json() for preset in service.session_presets] == EXPECTED_PRESETS


def test_ready_projects_session_presets_for_native_clients(tmp_path: Path) -> None:
    bridge, _capabilities = server(tmp_path)
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
        features = capabilities["features"]
        assert isinstance(features, dict)
        assert features["session_presets"] == EXPECTED_PRESETS
    finally:
        client.close()
        thread.join(timeout=2)

    assert errors == []
