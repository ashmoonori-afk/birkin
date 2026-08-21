from __future__ import annotations

import json
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import cast, final

import pytest

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
)
from birkin.native.protocol import NativeEnvelope, encode_frame
from birkin.native.server import NativeBridgeServer
from birkin.native.transport import receive_frame
from birkin.office.errors import DocumentError
from birkin.office.service import DocumentService
from birkin.workspace import WorkspaceService
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


def test_surface_revisions_gap_and_seeded_secret_redaction(tmp_path: Path) -> None:
    product = _product(tmp_path)
    secret = "sk-seeded_PHASE10_SECRET_123456789"
    product.browser.set_test_refusal(f"authorization=Bearer {secret}")

    first = product.snapshots({"browser_aside": 0, "computer_use": 0, "office": 0})
    assert [item.surface for item in first] == ["browser_aside", "computer_use", "office"]
    assert all(item.revision == 1 for item in first)
    encoded = json.dumps([item.payload for item in first], sort_keys=True).encode()
    assert secret.encode() not in encoded
    assert b"Bearer" not in encoded

    assert product.snapshots({"browser_aside": 1}) == ()
    product.browser.set_test_refusal("network_refused")
    recovered = product.snapshots({"browser_aside": 0})
    assert len(recovered) == 1
    assert recovered[0].revision == 2
    assert recovered[0].full_snapshot is True
    assert recovered[0].reset_reason == "revision_gap"


def test_browser_projection_has_private_generation_lease_frame_and_navigation(
    tmp_path: Path,
) -> None:
    product = _product(tmp_path)
    product.browser.acquire("macos:main", "human")
    payload = product.snapshots({"browser_aside": 0})[0].payload
    assert payload["profile"] == {"kind": "private_workspace", "generation": 7}
    control = _object(payload["control"])
    assert control["owner_kind"] == "human"
    assert control["epoch"] == 1
    assert payload["frame"] == {"ref": "frame:7:2", "revision": 2}
    assert _object(payload["navigation"])["display_url"] == "http://127.0.0.1:8123/"
    assert "profile_path" not in json.dumps(payload)


def test_browser_command_refuses_personal_profile_path(tmp_path: Path) -> None:
    product = _product(tmp_path)
    handler = product.handlers(lambda _kind, _payload: None)["browser.start"]
    with pytest.raises(ValueError, match="private workspace profile"):
        _ = handler({
            "profile_path": str(
                Path.home() / "Library/Application Support/Google/Chrome"
            )
        })


def test_computer_use_never_prompts_and_projects_bound_one_shot_expiry(
    tmp_path: Path,
) -> None:
    product = _product(tmp_path)
    computer = product.computer_use
    expires = datetime(2026, 8, 20, 12, 1, tzinfo=timezone.utc)
    computer.record_consent(
        grant_id="cu_grant_projection_123456",
        state="approved",
        action="click",
        application_ref="app:7",
        window_ref="window:9",
        prior_receipt="receipt:before",
        expires_at=expires,
    )
    computer.record_receipt("receipt:after", verdict="confirmed")

    payload = product.snapshots({"computer_use": 0})[0].payload
    status = _object(payload["status"])
    consent = _object(payload["consent"])
    assert status["permission_prompted"] is False
    assert status["permissions"] == {
        "accessibility": "not_determined",
        "screen_capture": "granted",
    }
    assert consent["one_shot"] is True
    assert consent["application_ref"] == "app:7"
    assert consent["window_ref"] == "window:9"
    assert consent["expires_at"] == expires.isoformat()
    assert payload["receipts"] == [{"receipt_ref": "receipt:after", "verdict": "confirmed"}]


def test_office_projection_create_and_secure_open_stay_in_service_jail(
    tmp_path: Path,
) -> None:
    product = _product(tmp_path)
    handlers = product.handlers(lambda _kind, _payload: None)
    created = handlers["office.create"]({
        "format": "docx",
        "content": {"paragraphs": ["Phase 10"]},
        "output_name": "phase-10.docx",
    })
    artifact = _object(created["document"])
    opened = handlers["office.open"]({"artifact": artifact})
    payload = product.snapshots({"office": 0})[0].payload
    opened_document = _object(opened["document"])
    source = _object(opened_document["source"])
    documents = _objects(payload["documents"])
    receipts = _objects(payload["receipts"])

    assert Path(cast(str, artifact["uri"])).is_relative_to(product.office.service.home)
    assert source["sha256"] == artifact["content_hash"]
    assert payload["inventory"]
    assert documents[0]["artifact_id"] == artifact["artifact_id"]
    assert [item["operation"] for item in receipts] == [
        "document_create", "document_open"
    ]
    with pytest.raises(DocumentError):
        _ = handlers["office.open"]({
            "artifact": {
                **artifact,
                "uri": str(tmp_path.parent / "outside.docx"),
            }
        })
    assert _object(product.office.snapshot()["refusal"])["code"] == "path_refused"


@final
class _FakeBrowserRuntime:
    """In-memory Browser Aside stand-in with the same generation/revision CAS."""

    def __init__(self) -> None:
        self._generation = 7
        self._revision = 3
        self._url = "http://127.0.0.1:8123/"

    def status(self) -> dict[str, object]:
        return {
            "live": True,
            "engine": "chromium",
            "browser_generation": self._generation,
            "browser_revision": self._revision,
            "frame_revision": self._revision,
            "display_url": self._url,
            "frame_ref": f"frame:{self._generation}:{self._revision}",
        }

    def start(
        self,
        *,
        actor_id: str = "human:web",
        control_epoch: int = 1,
    ) -> tuple[dict[str, object], bool]:
        del actor_id, control_epoch
        return self.status(), False

    def navigate(
        self,
        url: str,
        *,
        expected_generation: int,
        expected_revision: int,
    ) -> dict[str, object]:
        if expected_generation != self._generation:
            raise ValueError("browser generation is stale")
        if expected_revision != self._revision:
            raise ValueError("browser revision is stale")
        self._url = url
        self._revision += 1
        return self.status()


def _live_product(tmp_path: Path, browser: _FakeBrowserRuntime) -> (
    NativeProductSurfaceAuthority
):
    now = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)
    return NativeProductSurfaceAuthority(
        browser=BrowserSurfaceAuthority(
            browser,
            BrowserControlAuthority(lambda: now.timestamp()),
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


def test_product_mutations_push_live_surface_events_without_resubscribe(
    tmp_path: Path,
) -> None:
    """Given a subscribed client, When a browser navigation and an Office
    creation are committed, Then each mutation delivers a revisioned surface
    frame on the live connection."""
    browser = _FakeBrowserRuntime()
    product = _live_product(tmp_path, browser)
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
    client.settimeout(10)
    thread, errors = serve(
        bridge, server_socket, transport="uds", peer_uid=local_peer_uid()
    )
    try:
        client.sendall(encode_frame(hello(bootstrap_secret=None)))
        ready = receive_frame(client)
        capability = ready.body["capability"]
        assert isinstance(capability, dict)
        token = capability["token"]
        assert isinstance(token, str)
        client.sendall(encode_frame(envelope(
            "subscribe", frame_id="subscribe-live", body={
                "session_id": "session-1", "after_cursor": 0,
                "known_instance_id": None, "session_capability": token,
                "surfaces": {"browser_aside": 0, "computer_use": 0, "office": 0},
            }
        )))
        assert receive_frame(client).kind == "snapshot"
        baseline: dict[str, int] = {}
        for _index in range(3):
            frame = receive_frame(client)
            assert frame.kind == "surface_snapshot"
            surface = frame.body["surface"]
            revision = frame.body["revision"]
            assert isinstance(surface, str) and isinstance(revision, int)
            baseline[surface] = revision

        _send_product_command(
            client, token=token, command_id="browser-navigate-1", cursor=0,
            command_type="browser.navigate", payload={
                "url": "http://127.0.0.1:8123/live",
                "generation": 7,
                "revision": 3,
            },
        )
        navigated = _receive_kind(client, "surface_event")
        navigation = _object(_object(navigated.body["payload"])["navigation"])
        assert navigated.body["surface"] == "browser_aside"
        assert navigated.body["revision"] == baseline["browser_aside"] + 1
        assert navigation["display_url"] == "http://127.0.0.1:8123/live"

        _send_product_command(
            client, token=token, command_id="office-create-live", cursor=4,
            command_type="office.create", payload={
                "format": "docx",
                "content": {"paragraphs": ["Live surface"]},
                "output_name": "live-surface.docx",
            },
        )
        created = _receive_kind(client, "surface_event")
        documents = _objects(_object(created.body["payload"])["documents"])
        assert created.body["surface"] == "office"
        assert created.body["revision"] == baseline["office"] + 1
        assert len(documents) == 1
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
    *,
    token: str,
    command_id: str,
    cursor: int,
    command_type: str,
    payload: dict[str, object],
) -> None:
    client.sendall(encode_frame(envelope(
        "command", frame_id=f"frame-{command_id}", body={
            "session_capability": token,
            "command": {
                "protocol_version": 1,
                "command_id": command_id,
                "expected_cursor": cursor,
                "type": command_type,
                "payload": payload,
                "client_context": {"surface": "macos", "view_id": "office"},
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
        client.sendall(encode_frame(hello(bootstrap_secret=None)))
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

        _send_product_command(
            client, token=token, command_id="office-create-1", cursor=0,
            command_type="office.create", payload={
                "format": "docx",
                "content": {"paragraphs": ["Created through native socket"]},
                "output_name": "socket-created.docx",
            },
        )
        create_receipt = _receive_kind(client, "receipt")
        assert create_receipt.body["state"] == "completed"
        office_projection = product.office.snapshot()
        artifact = _objects(office_projection["documents"])[0]

        _send_product_command(
            client, token=token, command_id="office-open-1", cursor=4,
            command_type="office.open", payload={"artifact": artifact},
        )
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
