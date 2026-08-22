from __future__ import annotations

import socket
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


@final
class _FakeBrowserRuntime:
    """In-memory Browser Aside stand-in with generation and revision CAS."""

    def __init__(self) -> None:
        self._generation = 7
        self._revision = 3
        self._url = "http://127.0.0.1:8123/"
        self._live = True

    def status(self) -> dict[str, object]:
        return {
            "live": self._live,
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

    def close(self) -> dict[str, object]:
        self._live = False
        return self.status()


def _live_product(
    tmp_path: Path,
    browser: _FakeBrowserRuntime,
) -> NativeProductSurfaceAuthority:
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


def test_browser_history_reload_and_close_use_current_cas_identity(tmp_path: Path) -> None:
    browser = _FakeBrowserRuntime()
    product = _live_product(tmp_path, browser)
    handlers = product.handlers(lambda _kind, _payload: None)

    _ = handlers["browser.navigate"]({
        "url": "http://127.0.0.1:8123/one", "generation": 7, "revision": 3,
    })
    _ = handlers["browser.navigate"]({
        "url": "http://127.0.0.1:8123/two", "generation": 7, "revision": 4,
    })
    snapshot = product.browser.snapshot()
    history = _object(_object(snapshot["navigation"])["history"])
    assert history["entries"] == [
        "http://127.0.0.1:8123/", "http://127.0.0.1:8123/one",
        "http://127.0.0.1:8123/two",
    ]
    assert history["can_go_back"] is True

    _ = handlers["browser.back"]({"generation": 7, "revision": 5})
    _ = handlers["browser.reload"]({"generation": 7, "revision": 6})
    _ = handlers["browser.forward"]({"generation": 7, "revision": 7})
    _ = handlers["browser.close"]({})
    assert _object(product.browser.snapshot()["runtime"])["live"] is False


def test_unchanged_surface_payload_publishes_no_live_frame(tmp_path: Path) -> None:
    """Given a surface already published at a revision, When its canonical
    payload has not changed, Then no live frame is produced, and a later real
    change produces exactly the next revision."""
    product = _live_product(tmp_path, _FakeBrowserRuntime())

    first = product.live_snapshot("computer_use")
    assert first is not None
    assert first.revision == 1

    assert product.live_snapshot("computer_use") is None
    assert product.live_snapshot("computer_use") is None

    product.computer_use.record_receipt("receipt:1", verdict="allowed")
    changed = product.live_snapshot("computer_use")
    assert changed is not None
    assert changed.revision == first.revision + 1


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
        client.sendall(
            encode_frame(hello(bootstrap_secret=None, view_id="office"))
        )
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

        _send_product_command(client, token, WorkspaceCommand(
            protocol_version=PROTOCOL_VERSION,
            command_id="browser-navigate-1",
            expected_cursor=0,
            type="browser.navigate",
            payload={
                "url": "http://127.0.0.1:8123/live",
                "generation": 7,
                "revision": 3,
            },
            client_context=ClientContext(surface="macos", view_id="office"),
        ))
        navigated = _receive_kind(client, "surface_event")
        navigation = _object(_object(navigated.body["payload"])["navigation"])
        assert navigated.body["surface"] == "browser_aside"
        assert navigated.body["revision"] == baseline["browser_aside"] + 1
        assert navigation["display_url"] == "http://127.0.0.1:8123/live"

        _send_product_command(client, token, WorkspaceCommand(
            protocol_version=PROTOCOL_VERSION,
            command_id="office-create-live",
            expected_cursor=4,
            type="office.create",
            payload={
                "format": "docx",
                "content": {"paragraphs": ["Live surface"]},
                "output_name": "live-surface.docx",
            },
            client_context=ClientContext(surface="macos", view_id="office"),
        ))
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
