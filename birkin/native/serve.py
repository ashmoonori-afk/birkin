"""Production entry point that serves the local native application bridge."""

from __future__ import annotations

import errno
import json
import os
import signal
import sys
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Protocol, final

from birkin import __version__, config
from birkin.native.capability import BootstrapSecretStore
from birkin.native.endpoint import NativeBridgeEndpoint
from birkin.native.product_surfaces import SurfaceSnapshot
from birkin.native.server import NativeBridgeServer
from birkin.workspace.hub import EventSink, WorkspaceHub
from birkin.workspace.runtime_adapter import RuntimeWorkspaceAdapter
from birkin.workspace.service import CommandHandler

Announce = Callable[[str], None]

DEFAULT_SESSION_ID = "native-app"
_SUPPORTED_TRANSPORTS = ("uds", "loopback")

# Losing the listener is the one socket failure serving cannot survive: there
# is nothing left to accept on. Every other socket error belongs to a single
# connection or to momentary kernel pressure.
_LISTENER_LOST_ERRNOS = frozenset({errno.EBADF, errno.EINVAL, errno.ENOTSOCK})

# A ceiling on consecutive failures, so an unrecoverable listener that reports
# a recoverable errno ends the process instead of spinning on it forever.
MAX_CONSECUTIVE_ACCEPT_FAILURES = 64


class ServingEndpoint(Protocol):
    """The accept-and-serve surface one bridge lifecycle needs."""

    def serve_once(self) -> None: ...

    def close(self) -> None: ...


@final
class _SelectedSurfaceAuthority:
    """Project the product surfaces belonging to the selected session.

    Surfaces are per-session state, so the bridge must follow the hub's
    selection rather than bind to whichever session happened to start first.
    """

    def __init__(
        self,
        hub: WorkspaceHub,
        adapters: Mapping[str, RuntimeWorkspaceAdapter],
    ) -> None:
        self._hub = hub
        self._adapters = adapters

    def _current(self) -> RuntimeWorkspaceAdapter:
        return self._adapters[self._hub.snapshot().session_id]

    @property
    def surface_names(self) -> tuple[str, ...]:
        return self._current().surface_authority.surface_names

    def snapshots(
        self,
        requested: Mapping[str, int],
    ) -> tuple[SurfaceSnapshot, ...]:
        return self._current().surface_authority.snapshots(requested)

    def live_snapshot(self, surface: str) -> SurfaceSnapshot | None:
        return self._current().surface_authority.live_snapshot(surface)


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
        transport: str | None = None,
        session_id: str | None = None,
        root: Path | None = None,
    ) -> NativeServeOptions:
        resolved_transport = (
            "loopback" if os.name == "nt" else "uds"
        ) if transport is None else transport
        if resolved_transport not in _SUPPORTED_TRANSPORTS:
            raise ValueError(f"transport must be one of {_SUPPORTED_TRANSPORTS}")
        resolved_root = root or (config.birkin_home() / "native-bridge")
        return cls(
            transport=resolved_transport,
            session_id=session_id or DEFAULT_SESSION_ID,
            root=resolved_root.expanduser(),
        )


def _emit(announce: Announce, record: dict[str, object]) -> None:
    announce(json.dumps(record, separators=(",", ":")))


def _write_line(line: str) -> None:
    print(line, flush=True)


@final
class BridgeProcess:
    """One serving lifecycle: compose, announce, accept, and clean up."""

    def __init__(self, options: NativeServeOptions, announce: Announce) -> None:
        self._options = options
        self._announce = announce
        self._stopping = threading.Event()
        self._accept_failures = 0
        self._instance_id = uuid.uuid4().hex
        options.root.mkdir(parents=True, exist_ok=True)
        self._adapters: dict[str, RuntimeWorkspaceAdapter] = {}
        self._hub = WorkspaceHub(
            root=options.root / "workspace",
            handler_factory=self._session_handlers,
        )
        _session, _created = self._hub.create(options.session_id)
        self._capabilities = BootstrapSecretStore(options.root / "native")
        self._socket_path = options.root / "bridge.sock"
        self._bridge = NativeBridgeServer(
            self._hub,
            session_authority=self._hub,
            capabilities=self._capabilities,
            instance_id=self._instance_id,
            server_version=__version__,
            on_disconnect=self._revoke_terminal_leases,
            surface_authority=_SelectedSurfaceAuthority(
                self._hub, self._adapters
            ),
        )

    def _session_handlers(
        self,
        session_id: str,
        emit: EventSink,
    ) -> Mapping[str, CommandHandler]:
        """Give every session its own runtime, so a created session is real."""
        adapter = RuntimeWorkspaceAdapter(
            session_id,
            emit,
            workspace_root=self._options.root,
        )
        self._adapters[session_id] = adapter
        return adapter.handlers()

    def _revoke_terminal_leases(self) -> None:
        for adapter in list(self._adapters.values()):
            adapter.revoke_terminal_leases()

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

    @property
    def accept_failures(self) -> int:
        """Consecutive socket failures since a connection was last served."""
        return self._accept_failures

    def stop(self, endpoint: ServingEndpoint) -> None:
        self._stopping.set()
        endpoint.close()

    def close(self) -> None:
        """Release the workspace resources this lifecycle owns."""
        for adapter in list(self._adapters.values()):
            adapter.close()

    def run(self) -> int:
        endpoint = self._open()
        restore = _install_signal_handlers(lambda: self.stop(endpoint))
        try:
            _emit(self._announce, self._listening())
            while not self._stopping.is_set():
                self.serve_one(endpoint)
        finally:
            restore()
            endpoint.close()
            self.close()
            _emit(self._announce, {
                "event": "stopped",
                "socket_exists": self._socket_path.exists(),
                "discovery_exists": self._capabilities.endpoint_path.exists(),
            })
        return 0

    def serve_one(self, endpoint: ServingEndpoint) -> None:
        """Serve one client, surviving anything that client can provoke.

        This is the process boundary: a refusal must end the connection, never
        the bridge the packaged application depends on.
        """
        try:
            endpoint.serve_once()
        except OSError as exc:
            if self._stopping.is_set():
                return
            self._absorb_socket_error(exc)
            return
        except Exception as exc:  # noqa: BLE001 - service boundary
            if self._stopping.is_set():
                return
            _emit(self._announce, {
                "event": "connection_failed",
                "error": f"{type(exc).__name__}: {exc}"[:200],
            })
        self._accept_failures = 0

    def _absorb_socket_error(self, exc: OSError) -> None:
        """Keep serving a per-connection socket failure; stop when the
        listener itself is gone.

        A loaded kernel aborts individual accepts and a client may reset its
        own connection at any moment. Neither is a reason to end the bridge the
        packaged application depends on, and ending it would also spend that
        application's restart budget.
        """
        if exc.errno in _LISTENER_LOST_ERRNOS:
            raise exc
        self._accept_failures += 1
        if self._accept_failures > MAX_CONSECUTIVE_ACCEPT_FAILURES:
            raise exc
        _emit(self._announce, {
            "event": "accept_failed",
            "error": f"OSError({exc.errno}): {exc.strerror}"[:200],
            "consecutive_failures": self._accept_failures,
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
    return BridgeProcess(options, announce).run()


def main(argv: list[str] | None = None) -> int:
    """Serve the bridge directly, for use as ``python -m birkin.native.serve``."""
    from birkin.cli import main as cli_main

    return cli_main(["native-bridge", "serve", *(argv or sys.argv[1:])])


if __name__ == "__main__":
    raise SystemExit(main())
