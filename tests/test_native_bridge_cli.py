"""The shipped CLI serves the native bridge the packaged app connects to."""

from __future__ import annotations

import io
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TypeGuard, cast

import pytest

from birkin.cli import main
from birkin.native.protocol import NativeEnvelope, encode_frame
from birkin.native.transport import receive_frame
from tests.native_bridge_support import envelope, hello


_SHORT_TEMP_ROOT = (
    Path("/private/tmp")
    if Path("/private/tmp").is_dir()
    else Path(tempfile.gettempdir())
)


def _serve(root: Path, *, transport: str = "uds") -> subprocess.Popen[str]:
    environment = dict(os.environ)
    environment["BIRKIN_HOME"] = str(root / "home")
    return subprocess.Popen(
        [
            sys.executable, "-m", "birkin", "native-bridge", "serve",
            "--transport", transport, "--root", str(root / "bridge"),
            "--session-id", "cli-session",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
        cwd=Path(__file__).resolve().parent.parent,
    )


def _is_string_keyed_record(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def _readiness(process: subprocess.Popen[str]) -> dict[str, object]:
    stdout = cast(io.TextIOWrapper, process.stdout)
    assert stdout is not None
    line = stdout.readline()
    assert line, (process.stderr.read() if process.stderr else "no output")
    record = cast(object, json.loads(line))
    assert _is_string_keyed_record(record)
    return record


def test_native_bridge_help_exits_cleanly() -> None:
    """Given the shipped CLI, When the bridge help is requested, Then it
    exits successfully."""
    with pytest.raises(SystemExit) as exit_info:
        _ = main(["native-bridge", "serve", "--help"])

    assert exit_info.value.code == 0


def test_native_bridge_rejects_an_unsupported_transport() -> None:
    """Given the shipped CLI, When an unknown transport is requested, Then it
    refuses with the argument-error exit code."""
    with pytest.raises(SystemExit) as exit_info:
        _ = main(["native-bridge", "serve", "--transport", "quic"])

    assert exit_info.value.code == 2


def test_module_entry_point_serves_the_bridge_cli() -> None:
    """Given the bundled helper invoked as a module, When it is asked for
    help, Then it serves the bridge CLI instead of exiting silently."""
    result = subprocess.run(
        [sys.executable, "-m", "birkin.native.serve", "--help"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0
    assert "--transport" in result.stdout


def test_module_entry_point_rejects_an_unsupported_transport() -> None:
    """Given the bundled helper invoked as a module, When the transport is
    unsupported, Then it exits non-zero instead of reporting success."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "birkin.native.serve",
            "--transport",
            "carrier-pigeon",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode != 0


def test_native_bridge_serves_a_real_connection_and_cleans_up() -> None:
    """Given the shipped CLI bridge, When a client completes a handshake and
    the bridge is asked to stop, Then it announced a live endpoint, served the
    connection, and removed the endpoint on exit."""
    # A Unix socket path is bounded by the platform, so this suite keeps its
    # own short per-run root instead of the deep pytest temporary directory.
    root = Path(tempfile.mkdtemp(prefix="bk-cli-", dir=_SHORT_TEMP_ROOT))
    process = _serve(root)
    try:
        record = _readiness(process)
        assert record["event"] == "listening"
        assert record["transport"] == "uds"
        assert record["pid"] == process.pid
        socket_path = record["socket_path"]
        assert isinstance(socket_path, str)

        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(15)
        client.connect(socket_path)
        try:
            client.sendall(encode_frame(hello(bootstrap_secret=None)))
            ready = receive_frame(client)
            assert ready.kind == "ready"
            capability = ready.body["capability"]
            assert isinstance(capability, dict)
            token = capability["token"]
            assert isinstance(token, str)
            client.sendall(encode_frame(envelope(
                "subscribe", frame_id="subscribe-cli", body={
                    "session_id": "cli-session", "after_cursor": 0,
                    "known_instance_id": None, "session_capability": token,
                    "surfaces": {},
                },
            )))
            assert receive_frame(client).kind == "snapshot"
        finally:
            client.close()

        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=30) == 0
        assert not Path(socket_path).exists()
    finally:
        if process.poll() is None:
            process.kill()
            _ = process.wait(timeout=10)
        shutil.rmtree(root, ignore_errors=True)


def _command(
    client: socket.socket,
    *,
    token: str,
    frame_id: str,
    command_id: str,
    cursor: int,
    command_type: str,
    payload: dict[str, object],
) -> None:
    client.sendall(encode_frame(envelope(
        "command", frame_id=frame_id, body={
            "session_capability": token,
            "command": {
                "protocol_version": 1,
                "command_id": command_id,
                "expected_cursor": cursor,
                "type": command_type,
                "payload": payload,
                "client_context": {"surface": "macos", "view_id": "sessions"},
            },
        },
    )))


def _await(client: socket.socket, kind: str) -> object:
    for _index in range(32):
        frame = receive_frame(client)
        if frame.kind == kind:
            return frame
        if frame.kind == "error":
            raise AssertionError(frame.body)
    raise AssertionError(f"did not receive {kind}")


def test_served_bridge_creates_selects_and_serves_a_new_session() -> None:
    """Given the shipped bridge, When the app creates and selects a session,
    Then session.create is advertised, accepted, and the new session serves
    its own projection."""
    root = Path(tempfile.mkdtemp(prefix="bk-session-", dir=_SHORT_TEMP_ROOT))
    process = _serve(root)
    try:
        record = _readiness(process)
        socket_path = record["socket_path"]
        assert isinstance(socket_path, str)
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(30)
        client.connect(socket_path)
        try:
            client.sendall(
                encode_frame(hello(bootstrap_secret=None, view_id="sessions"))
            )
            ready = receive_frame(client)
            capabilities = ready.body["capabilities"]
            assert isinstance(capabilities, dict)
            commands = capabilities["commands"]
            assert isinstance(commands, list)
            assert "session.create" in commands
            capability = ready.body["capability"]
            assert isinstance(capability, dict)
            token = capability["token"]
            assert isinstance(token, str)

            client.sendall(encode_frame(envelope(
                "subscribe", frame_id="subscribe-first", body={
                    "session_id": "cli-session", "after_cursor": 0,
                    "known_instance_id": None, "session_capability": token,
                    "surfaces": {},
                },
            )))
            snapshot = receive_frame(client)
            assert snapshot.kind == "snapshot"
            cursor = snapshot.body["cursor"]
            assert isinstance(cursor, int)

            _command(
                client, token=token, frame_id="frame-create",
                command_id="create-second", cursor=cursor,
                command_type="session.create",
                payload={"session_id": "second-session"},
            )
            created = _await(client, "receipt")
            assert isinstance(created, NativeEnvelope)
            assert created.body["outcome"] == "accepted"
            after_create = created.body["result_event_cursor"]
            assert isinstance(after_create, int)

            _command(
                client, token=token, frame_id="frame-select",
                command_id="select-second", cursor=after_create,
                command_type="session.select",
                payload={"session_id": "second-session"},
            )
            selected = _await(client, "receipt")
            assert isinstance(selected, NativeEnvelope)
            assert selected.body["outcome"] == "accepted"

            client.sendall(encode_frame(envelope(
                "subscribe", frame_id="subscribe-second", body={
                    "session_id": "second-session", "after_cursor": 0,
                    "known_instance_id": None, "session_capability": token,
                    "surfaces": {},
                },
            )))
            switched = _await(client, "snapshot")
            assert isinstance(switched, NativeEnvelope)
            assert switched.body["session_id"] == "second-session"
        finally:
            client.close()

        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=30) == 0
    finally:
        if process.poll() is None:
            process.kill()
            _ = process.wait(timeout=10)
        shutil.rmtree(root, ignore_errors=True)
