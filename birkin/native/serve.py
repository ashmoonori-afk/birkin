"""Production entry point that serves the local native application bridge."""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import final

from birkin import __version__, config
from birkin.native.capability import BootstrapSecretStore
from birkin.native.endpoint import NativeBridgeEndpoint
from birkin.native.server import NativeBridgeServer
from birkin.workspace.runtime_adapter import RuntimeWorkspaceAdapter
from birkin.workspace.service import WorkspaceService

Announce = Callable[[str], None]

DEFAULT_SESSION_ID = "native-app"
_SUPPORTED_TRANSPORTS = ("uds", "loopback")


@final
@dataclass(frozen=True, slots=True)
class NativeServeOptions:
    """The resolved identity of one bridge process."""

    transport: str
    session_id: str
    root: Path

    @classmethod
    def resolve(
        cls,
        *,
        transport: str = "uds",
        session_id: str | None = None,
        root: Path | None = None,
    ) -> NativeServeOptions:
        if transport not in _SUPPORTED_TRANSPORTS:
            raise ValueError(f"transport must be one of {_SUPPORTED_TRANSPORTS}")
        resolved_root = root or (config.birkin_home() / "native-bridge")
        return cls(
            transport=transport,
            session_id=session_id or DEFAULT_SESSION_ID,
            root=resolved_root.expanduser(),
        )


def _emit(announce: Announce, record: dict[str, object]) -> None:
    announce(json.dumps(record, separators=(",", ":")))


def _write_line(line: str) -> None:
    print(line, flush=True)


@final
class _BridgeProcess:
    """One serving lifecycle: compose, announce, accept, and clean up."""

    def __init__(self, options: NativeServeOptions, announce: Announce) -> None:
        self._options = options
        self._announce = announce
        self._stopping = threading.Event()
        self._instance_id = uuid.uuid4().hex
        options.root.mkdir(parents=True, exist_ok=True)
        self._service = WorkspaceService(
            root=options.root / "workspace",
            session_id=options.session_id,
            handlers={},
        )
        self._adapter = RuntimeWorkspaceAdapter(
            options.session_id,
            self._service.emit,
            workspace_root=options.root,
        )
        self._service.set_handlers(self._adapter.handlers())
        self._capabilities = BootstrapSecretStore(options.root / "native")
        self._socket_path = options.root / "bridge.sock"
        self._bridge = NativeBridgeServer(
            self._service,
            capabilities=self._capabilities,
            instance_id=self._instance_id,
            server_version=__version__,
            on_disconnect=self._adapter.revoke_terminal_leases,
            surface_authority=self._adapter.surface_authority,
        )

    def _open(self) -> NativeBridgeEndpoint:
        if self._options.transport == "uds":
            return NativeBridgeEndpoint.uds(
                self._bridge, socket_path=self._socket_path
            )
        return NativeBridgeEndpoint.loopback(
            self._bridge,
            capabilities=self._capabilities,
            instance_id=self._instance_id,
            server_version=__version__,
        )

    def _listening(self) -> dict[str, object]:
        record: dict[str, object] = {
            "event": "listening",
            "transport": self._options.transport,
            "pid": os.getpid(),
            "root": str(self._options.root),
            "session_id": self._options.session_id,
            "instance_id": self._instance_id,
            "server_version": __version__,
        }
        if self._options.transport == "uds":
            record["socket_path"] = str(self._socket_path)
        else:
            record["discovery_path"] = str(self._capabilities.endpoint_path)
        return record

    def stop(self, endpoint: NativeBridgeEndpoint) -> None:
        self._stopping.set()
        endpoint.close()

    def run(self) -> int:
        endpoint = self._open()
        restore = _install_signal_handlers(lambda: self.stop(endpoint))
        try:
            _emit(self._announce, self._listening())
            while not self._stopping.is_set():
                self._serve_one(endpoint)
        finally:
            restore()
            endpoint.close()
            self._adapter.close()
            _emit(self._announce, {
                "event": "stopped",
                "socket_exists": self._socket_path.exists(),
                "discovery_exists": self._capabilities.endpoint_path.exists(),
            })
        return 0

    def _serve_one(self, endpoint: NativeBridgeEndpoint) -> None:
        """Serve one client, surviving anything that client can provoke.

        This is the process boundary: a refusal must end the connection, never
        the bridge the packaged application depends on.
        """
        try:
            endpoint.serve_once()
        except OSError:
            if not self._stopping.is_set():
                raise
        except Exception as exc:  # noqa: BLE001 - service boundary
            if self._stopping.is_set():
                return
            _emit(self._announce, {
                "event": "connection_failed",
                "error": f"{type(exc).__name__}: {exc}"[:200],
            })


def _install_signal_handlers(stop: Callable[[], None]) -> Callable[[], None]:
    def handle(_signum: int, _frame: FrameType | None) -> None:
        stop()

    previous = [
        (number, signal.signal(number, handle))
        for number in (signal.SIGTERM, signal.SIGINT)
    ]

    def restore() -> None:
        for number, handler in previous:
            _ = signal.signal(number, handler)

    return restore


def serve_bridge(
    options: NativeServeOptions,
    *,
    announce: Announce = _write_line,
) -> int:
    """Serve the authenticated local bridge until the process is stopped."""
    return _BridgeProcess(options, announce).run()


def main(argv: list[str] | None = None) -> int:
    """Serve the bridge directly, for use as ``python -m birkin.native.serve``."""
    from birkin.cli import main as cli_main

    return cli_main(["native-bridge", "serve", *(argv or sys.argv[1:])])
