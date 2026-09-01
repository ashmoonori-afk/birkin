"""The bridge process survives what the kernel and clients do to its socket."""

from __future__ import annotations

import errno
import socket
from pathlib import Path
from typing import final

import pytest

from birkin.native.capability import BootstrapSecretStore
from birkin.native.serve import (
    MAX_CONSECUTIVE_ACCEPT_FAILURES,
    BridgeProcess,
    NativeServeOptions,
)
from birkin.native.server import NativeBridgeServer
from birkin.workspace import WorkspaceService
from tests.native_bridge_support import local_peer_uid, serve


@final
class _ScriptedEndpoint:
    """An endpoint whose accept fails the way a loaded kernel makes it fail."""

    def __init__(self, failures: list[OSError]) -> None:
        self._failures = failures
        self.served = 0

    def serve_once(self) -> None:
        if self._failures:
            raise self._failures.pop(0)
        self.served += 1

    def close(self) -> None:
        return None


def _process(tmp_path: Path) -> BridgeProcess:
    return BridgeProcess(
        NativeServeOptions.resolve(session_id="reliability", root=tmp_path),
        lambda _line: None,
    )


def _aborted() -> OSError:
    return OSError(errno.ECONNABORTED, "software caused connection abort")


def test_aborted_accept_keeps_the_bridge_serving(tmp_path: Path) -> None:
    """Given an accept the kernel aborts, When the bridge serves again, Then
    it keeps serving instead of ending the process."""
    process = _process(tmp_path)
    endpoint = _ScriptedEndpoint([_aborted()])
    try:
        process.serve_one(endpoint)
        process.serve_one(endpoint)
    finally:
        process.close()
    assert endpoint.served == 1


def test_client_reset_keeps_the_bridge_serving(tmp_path: Path) -> None:
    """Given a client that resets its own connection, When the bridge serves
    again, Then the reset ends that connection and not the bridge."""
    process = _process(tmp_path)
    endpoint = _ScriptedEndpoint(
        [OSError(errno.ECONNRESET, "connection reset by peer")]
    )
    try:
        process.serve_one(endpoint)
        process.serve_one(endpoint)
    finally:
        process.close()
    assert endpoint.served == 1


def test_a_served_connection_clears_the_failure_budget(tmp_path: Path) -> None:
    """Given accepts that fail and then recover, When failures resume, Then
    the budget starts over rather than carrying the earlier failures."""
    process = _process(tmp_path)
    endpoint = _ScriptedEndpoint(
        [_aborted() for _ in range(MAX_CONSECUTIVE_ACCEPT_FAILURES)]
    )
    try:
        for _ in range(MAX_CONSECUTIVE_ACCEPT_FAILURES):
            process.serve_one(endpoint)
        assert process.accept_failures == MAX_CONSECUTIVE_ACCEPT_FAILURES
        process.serve_one(endpoint)
        assert process.accept_failures == 0
        assert endpoint.served == 1
    finally:
        process.close()


def test_relentless_accept_failure_stops_the_bridge(tmp_path: Path) -> None:
    """Given accepts that never recover, When the failure budget is spent,
    Then the bridge stops instead of spinning on the listener forever."""
    process = _process(tmp_path)
    endpoint = _ScriptedEndpoint(
        [_aborted() for _ in range(MAX_CONSECUTIVE_ACCEPT_FAILURES + 1)]
    )
    try:
        for _ in range(MAX_CONSECUTIVE_ACCEPT_FAILURES):
            process.serve_one(endpoint)
        with pytest.raises(OSError) as spent:
            process.serve_one(endpoint)
        assert spent.value.errno == errno.ECONNABORTED
    finally:
        process.close()


def test_a_silent_client_cannot_hold_the_accept_loop(tmp_path: Path) -> None:
    """Given a client that connects and never says hello, When the pre-hello
    deadline passes, Then the bridge releases the connection instead of
    holding the serial accept loop against every other client."""
    source = WorkspaceService(
        root=tmp_path / "workspace", session_id="session-1", handlers={}
    )
    bridge = NativeBridgeServer(
        source,
        capabilities=BootstrapSecretStore(tmp_path / "native"),
        instance_id="instance-1",
        server_version="1.0.0",
        hello_timeout=0.25,
    )
    server_socket, client = socket.socketpair()
    thread, errors = serve(
        bridge,
        server_socket,
        transport="uds",
        peer_uid=local_peer_uid(),
    )
    try:
        thread.join(timeout=30)
        assert not thread.is_alive()
    finally:
        client.close()
        thread.join(timeout=5)
    assert errors == []


def test_lost_listener_stops_the_bridge(tmp_path: Path) -> None:
    """Given a listener that no longer exists, When the bridge tries to serve,
    Then it stops, because there is nothing left to accept on."""
    process = _process(tmp_path)
    endpoint = _ScriptedEndpoint([OSError(errno.EBADF, "bad file descriptor")])
    try:
        with pytest.raises(OSError) as lost:
            process.serve_one(endpoint)
        assert lost.value.errno == errno.EBADF
    finally:
        process.close()
