from __future__ import annotations

import socket
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import cast, final

from birkin.browser_aside_control import BrowserControlAuthority
from birkin.computer_use.capability_types import (
    DisplayServer,
    PermissionState,
    PlatformProbe,
)
from birkin.native.capability import BootstrapSecretStore
from birkin.native.product_surfaces import (
    BrowserSurfaceAuthority,
    ComputerUseSurfaceAuthority,
    NativeProductSurfaceAuthority,
    OfficeSurfaceAuthority,
    SurfaceSnapshot,
)
from birkin.native.protocol import NativeEnvelope, encode_frame
from birkin.native.server import NativeBridgeServer
from birkin.native.transport import receive_frame
from birkin.office.service import DocumentService
from birkin.workspace import WorkspaceService
from birkin.workspace.contracts import ClientContext, PROTOCOL_VERSION, WorkspaceCommand
from tests.native_bridge_support import envelope, hello, local_peer_uid, serve


def _object(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _objects(value: object) -> list[dict[str, object]]:
    assert isinstance(value, list)
    return [_object(item) for item in cast(list[object], value)]


def _product(tmp_path: Path) -> NativeProductSurfaceAuthority:
    now = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)
    return NativeProductSurfaceAuthority(
        browser=BrowserSurfaceAuthority.for_testing(
            workspace_id="session-1",
            status={
                "live": True,
                "browser_generation": 7,
                "browser_revision": 3,
                "frame_revision": 2,
                "display_url": "http://127.0.0.1:8123/",
                "frame_ref": "frame:7:2",
                "frame_digest": "safe-digest",
            },
            control=BrowserControlAuthority(lambda: now.timestamp()),
            now=lambda: now,
        ),
        computer_use=ComputerUseSurfaceAuthority(
            probe=PlatformProbe(
                platform="darwin",
                display_server=DisplayServer.QUARTZ,
                interactive=True,
                accessibility=PermissionState.NOT_DETERMINED,
                screen_capture=PermissionState.GRANTED,
                responsible_process="Birkin",
            ),
            now=lambda: now,
        ),
        office=OfficeSurfaceAuthority(DocumentService(tmp_path / "office")),
    )


@final
class _FailingSurfaceProjection:
    """A surface projection that fails the way a serialization bug would."""

    def __init__(self, inner: NativeProductSurfaceAuthority) -> None:
        self._inner = inner

    @property
    def surface_names(self) -> tuple[str, ...]:
        return self._inner.surface_names

    def snapshots(
        self,
        requested: Mapping[str, int],
    ) -> tuple[SurfaceSnapshot, ...]:
        return self._inner.snapshots(requested)

    def live_snapshot(self, surface: str) -> SurfaceSnapshot | None:
        raise RuntimeError(f"surface projection failed for {surface}")


def test_surface_projection_failure_keeps_the_canonical_command_accepted(
    tmp_path: Path,
) -> None:
    """Given a surface projection that raises, When a canonical command
    commits, Then the shell still receives an accepted receipt for it."""
    product = _product(tmp_path)
    source = WorkspaceService(
        root=tmp_path / "workspace", session_id="session-1", handlers={}
    )
    source.set_handlers(product.handlers(source.emit))
    bridge = NativeBridgeServer(
        source,
        capabilities=BootstrapSecretStore(tmp_path / "native"),
        instance_id="instance-1", server_version="1.0.0",
        surface_authority=_FailingSurfaceProjection(product),
    )
    server_socket, client = socket.socketpair()
    client.settimeout(10)
    thread, errors = serve(
        bridge, server_socket, transport="uds", peer_uid=local_peer_uid()
    )
    try:
        client.sendall(
            encode_frame(hello(bootstrap_secret=None, view_id="office"))
        )
        ready = receive_frame(client)
        capability = ready.body["capability"]
        assert isinstance(capability, dict)
        token = capability["token"]
        assert isinstance(token, str)
        client.sendall(encode_frame(envelope(
            "subscribe", frame_id="subscribe-isolated", body={
                "session_id": "session-1", "after_cursor": 0,
                "known_instance_id": None, "session_capability": token,
                "surfaces": {"office": 0},
            }
        )))
        assert receive_frame(client).kind == "snapshot"
        assert receive_frame(client).kind == "surface_snapshot"

        _send_product_command(client, token, WorkspaceCommand(
            protocol_version=PROTOCOL_VERSION,
            command_id="office-create-isolated",
            expected_cursor=0,
            type="office.create",
            payload={
                "format": "docx",
                "content": {"paragraphs": ["Isolated"]},
                "output_name": "isolated.docx",
            },
            client_context=ClientContext(surface="macos", view_id="office"),
        ))
        receipt = _receive_kind(client, "receipt")
        assert receipt.body["outcome"] == "accepted"
    finally:
        client.close()
        thread.join(timeout=5)
    assert errors == []


def _receive_kind(client: socket.socket, kind: str) -> NativeEnvelope:
    for _ in range(24):
        message = receive_frame(client)
        if message.kind == kind:
            return message
        if message.kind == "error":
            raise AssertionError(message.body)
    raise AssertionError(f"did not receive {kind}")


def _send_product_command(
    client: socket.socket,
    token: str,
    command: WorkspaceCommand,
) -> None:
    client.sendall(encode_frame(envelope(
        "command", frame_id=f"frame-{command.command_id}", body={
            "session_capability": token,
            "command": {
                "protocol_version": command.protocol_version,
                "command_id": command.command_id,
                "expected_cursor": command.expected_cursor,
                "type": command.type,
                "payload": command.payload,
                "client_context": command.client_context.to_json(),
            },
        }
    )))


def test_real_socket_subscribe_emits_negotiated_surface_snapshots(tmp_path: Path) -> None:
    product = _product(tmp_path)
    source = WorkspaceService(
        root=tmp_path / "workspace", session_id="session-1", handlers={}
    )
    source.set_handlers(product.handlers(source.emit))
    bridge = NativeBridgeServer(
        source,
        capabilities=BootstrapSecretStore(tmp_path / "native"),
        instance_id="instance-1", server_version="1.0.0",
        surface_authority=product,
    )
    server_socket, client = socket.socketpair()
    thread, errors = serve(
        bridge, server_socket, transport="uds", peer_uid=local_peer_uid()
    )
    try:
        client.sendall(
            encode_frame(hello(bootstrap_secret=None, view_id="office"))
        )
        ready = receive_frame(client)
        capability = ready.body["capability"]
        assert isinstance(capability, dict)
        token = capability["token"]
        assert isinstance(token, str)
        capabilities = _object(ready.body["capabilities"])
        features = _object(capabilities["features"])
        assert features["surfaces"] == [
            "browser_aside", "computer_use", "office"
        ]
        client.sendall(encode_frame(envelope(
            "subscribe", frame_id="subscribe-products", body={
                "session_id": "session-1", "after_cursor": 0,
                "known_instance_id": None, "session_capability": token,
                "surfaces": {"browser_aside": 0, "computer_use": 0, "office": 0},
            }
        )))
        assert receive_frame(client).kind == "snapshot"
        surfaces = [receive_frame(client) for _ in range(3)]
        assert [item.kind for item in surfaces] == ["surface_snapshot"] * 3
        assert [item.body["surface"] for item in surfaces] == [
            "browser_aside", "computer_use", "office"
        ]

        _send_product_command(client, token, WorkspaceCommand(
            protocol_version=PROTOCOL_VERSION,
            command_id="office-create-1",
            expected_cursor=0,
            type="office.create",
            payload={
                "format": "docx",
                "content": {"paragraphs": ["Created through native socket"]},
                "output_name": "socket-created.docx",
            },
            client_context=ClientContext(surface="macos", view_id="office"),
        ))
        create_receipt = _receive_kind(client, "receipt")
        assert create_receipt.body["state"] == "completed"
        office_projection = product.office.snapshot()
        artifact = _objects(office_projection["documents"])[0]

        _send_product_command(client, token, WorkspaceCommand(
            protocol_version=PROTOCOL_VERSION,
            command_id="office-open-1",
            expected_cursor=4,
            type="office.open",
            payload={"artifact": artifact},
            client_context=ClientContext(surface="macos", view_id="office"),
        ))
        open_receipt = _receive_kind(client, "receipt")
        assert open_receipt.body["state"] == "completed"
        receipts = _objects(product.office.snapshot()["receipts"])
        assert [receipt["operation"] for receipt in receipts] == [
            "document_create", "document_open"
        ]
    finally:
        client.close()
        thread.join(timeout=2)
    assert errors == []
