from __future__ import annotations

import errno
import hashlib
import os
import socket
from pathlib import Path
from typing import cast

import pytest

from birkin.native.capability import BootstrapSecretStore
from birkin.native.jailed_import import MAX_IMPORT_BYTES, JailedImportAuthority
from birkin.native.protocol import encode_frame
from birkin.native.server import NativeBridgeServer
from birkin.native.transport import receive_frame
from birkin.workspace import WorkspaceService
from birkin.workspace.contracts import ProtocolError
from tests.native_bridge_support import envelope, handshake, local_peer_uid, serve


def test_import_copies_external_file_and_returns_only_canonical_jail_identity(
    tmp_path: Path,
) -> None:
    source = tmp_path / "outside" / "quarterly-plan.txt"
    source.parent.mkdir()
    source.write_text("canonical attachment", encoding="utf-8")
    jail = tmp_path / "workspace" / "imports"
    authority = JailedImportAuthority(jail)

    result = authority.import_file({"source_path": str(source)})

    reference = result["reference"]
    receipt = result["receipt"]
    assert isinstance(reference, dict)
    assert isinstance(receipt, dict)
    jailed_path = jail / str(reference["jail_name"])
    assert jailed_path.read_bytes() == source.read_bytes()
    assert reference == {
        "kind": "workspace_import",
        "import_id": receipt["import_id"],
        "display_name": "quarterly-plan.txt",
        "jail_name": jailed_path.name,
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "byte_count": len(source.read_bytes()),
    }
    encoded = repr(result)
    assert str(source) not in encoded
    assert "source_path" not in encoded
    assert receipt["operation"] == "file.import"
    assert receipt["copied"] is True


def test_import_refuses_regular_file_exceeding_canonical_byte_limit(
    tmp_path: Path,
) -> None:
    source = tmp_path / "outside" / "oversized.bin"
    _ = source.parent.mkdir()
    with source.open("wb") as stream:
        _ = stream.truncate(MAX_IMPORT_BYTES + 1)
    authority = JailedImportAuthority(tmp_path / "jail")

    with pytest.raises(ProtocolError, match="exceeds byte limit"):
        _ = authority.import_file({"source_path": str(source)})

    assert list(authority.jail.iterdir()) == []


def test_import_removes_partial_destination_when_storage_write_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "outside" / "write-error.bin"
    _ = source.parent.mkdir()
    _ = source.write_bytes(b"partial destination")
    authority = JailedImportAuthority(tmp_path / "jail")
    original_write = os.write
    write_attempts = 0

    def write_partial_chunk_then_fail(fd: int, data: memoryview) -> int:
        nonlocal write_attempts
        write_attempts += 1
        if write_attempts == 1:
            return original_write(fd, data[:1])
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(os, "write", write_partial_chunk_then_fail)

    with pytest.raises(OSError, match="No space left on device"):
        _ = authority.import_file({"source_path": str(source)})

    assert list(authority.jail.iterdir()) == []


def test_import_accepts_regular_file_at_canonical_byte_limit(tmp_path: Path) -> None:
    source = tmp_path / "outside" / "exact-limit.bin"
    _ = source.parent.mkdir()
    with source.open("wb") as stream:
        _ = stream.truncate(MAX_IMPORT_BYTES)
    authority = JailedImportAuthority(tmp_path / "jail")

    result = authority.import_file({"source_path": str(source)})

    reference = result["reference"]
    receipt = result["receipt"]
    assert isinstance(reference, dict)
    assert isinstance(receipt, dict)
    assert reference["byte_count"] == MAX_IMPORT_BYTES
    assert receipt["byte_count"] == MAX_IMPORT_BYTES


def test_import_refuses_direct_destination_and_non_file_sources(tmp_path: Path) -> None:
    source = tmp_path / "outside.txt"
    source.write_text("safe", encoding="utf-8")
    authority = JailedImportAuthority(tmp_path / "jail")

    with pytest.raises(ProtocolError, match="canonical source_path"):
        authority.import_file({
            "source_path": str(source),
            "destination_path": str(tmp_path / "passthrough.txt"),
        })
    with pytest.raises(ProtocolError, match="regular file"):
        authority.import_file({"source_path": str(tmp_path)})


def test_import_handler_is_strict_and_advertisable(tmp_path: Path) -> None:
    source = tmp_path / "drop.txt"
    source.write_text("drop", encoding="utf-8")
    authority = JailedImportAuthority(tmp_path / "jail")

    handlers = authority.handlers()

    assert set(handlers) == {"file.import"}
    result = handlers["file.import"]({"source_path": str(source)})
    assert isinstance(result["reference"], dict)


def test_real_bridge_advertises_import_and_emits_canonical_copy_receipt(
    tmp_path: Path,
) -> None:
    dropped = tmp_path / "external" / "drop.txt"
    dropped.parent.mkdir()
    dropped.write_text("bridge copy", encoding="utf-8")
    authority = JailedImportAuthority(tmp_path / "workspace" / "imports")
    workspace = WorkspaceService(
        root=tmp_path / "journal",
        session_id="session-1",
        handlers=authority.handlers(),
    )
    bridge = NativeBridgeServer(
        workspace,
        capabilities=BootstrapSecretStore(tmp_path / "native"),
        instance_id="instance-import",
        server_version="1.0.0",
    )
    server_socket, client = socket.socketpair()
    thread, errors = serve(
        bridge, server_socket, transport="uds", peer_uid=local_peer_uid()
    )
    try:
        token = handshake(client, view_id="composer")
        client.sendall(encode_frame(envelope(
            "command",
            frame_id="frame-import",
            body={
                "session_capability": token,
                "command": {
                    "protocol_version": 1,
                    "command_id": "import-drop",
                    "expected_cursor": workspace.snapshot().cursor,
                    "type": "file.import",
                    "payload": {"source_path": str(dropped)},
                    "client_context": {"surface": "macos", "view_id": "composer"},
                },
            },
        )))
        command_receipt = None
        for _ in range(12):
            message = receive_frame(client)
            if message.kind == "receipt":
                command_receipt = message.body
                break
        assert command_receipt is not None
        assert command_receipt["state"] == "completed"
        completed = next(
            event for event in workspace.events()
            if event.type == "command.completed" and event.command_id == "import-drop"
        )
        result = cast(dict[str, object], completed.payload["result"])
        assert str(dropped) not in repr(result)
        reference = cast(dict[str, object], result["reference"])
        assert (authority.jail / str(reference["jail_name"])).read_text() == "bridge copy"
    finally:
        client.close()
        thread.join(timeout=2)
    assert errors == []
