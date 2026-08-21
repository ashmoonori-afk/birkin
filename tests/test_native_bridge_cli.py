"""The shipped CLI serves the native bridge the packaged app connects to."""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from birkin.cli import main
from birkin.native.protocol import encode_frame
from birkin.native.transport import receive_frame
from tests.native_bridge_support import envelope, hello


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


def _readiness(process: subprocess.Popen[str]) -> dict[str, object]:
    assert process.stdout is not None
    line = process.stdout.readline()
    assert line, (process.stderr.read() if process.stderr else "no output")
    record = json.loads(line)
    assert isinstance(record, dict)
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
    root = Path(tempfile.mkdtemp(prefix="bk-cli-", dir="/private/tmp"))
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
