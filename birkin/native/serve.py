"""Production entry point that serves the local native application bridge."""

from __future__ import annotations

import argparse
import errno
import os
import threading
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, final

from birkin import __version__, config
from birkin.native.capability import BootstrapSecretStore
from birkin.native.endpoint import NativeBridgeEndpoint
from birkin.native.serve_announce import (
    Announce,
    connection_failure,
    emit as _emit,
    install_signal_handlers,
    listening_record,
    ownership_callbacks,
    ownership_from_environment,
    start_ownership_monitor,
    write_line as _write_line,
)
from birkin.native.serve_surfaces import (
    SelectedSurfaceAuthority as _SelectedSurfaceAuthority,
)
from birkin.native.server import NativeBridgeServer
from birkin.workspace.hub import EventSink, WorkspaceHub
from birkin.workspace.runtime_adapter import RuntimeWorkspaceAdapter
from birkin.workspace.service import CommandHandler

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
        platform_name: str | None = None,
    ) -> NativeServeOptions:
        resolved_platform = os.name if platform_name is None else platform_name
        resolved_transport = (
            ("loopback" if resolved_platform == "nt" else "uds")
            if transport is None
            else transport
        )
        if resolved_transport not in _SUPPORTED_TRANSPORTS:
            raise ValueError(f"transport must be one of {_SUPPORTED_TRANSPORTS}")
        resolved_root = root or (config.birkin_home() / "native-bridge")
        return cls(
            transport=resolved_transport,
            session_id=session_id or DEFAULT_SESSION_ID,
            root=resolved_root.expanduser(),
        )


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
        self._ownership = ownership_from_environment(
            options.root, instance_id=self._instance_id, pid=os.getpid()
        )
        self._adapters: dict[str, RuntimeWorkspaceAdapter] = {}
        self._hub = WorkspaceHub(
            root=options.root / "workspace",
            handler_factory=self._session_handlers,
        )
        _session, _created = self._hub.create(options.session_id)
        self._hub.restore_existing()
        self._capabilities = BootstrapSecretStore(options.root / "native")
        self._socket_path = options.root / "bridge.sock"
        on_authenticated, on_connection_closed = ownership_callbacks(
            self._ownership
        )
        self._bridge = NativeBridgeServer(
            self._hub,
            session_authority=self._hub,
            capabilities=self._capabilities,
            instance_id=self._instance_id,
            server_version=__version__,
            on_disconnect=self._revoke_terminal_leases,
            on_authenticated=on_authenticated,
            on_connection_closed=on_connection_closed,
            surface_authority=_SelectedSurfaceAuthority(self._hub, self._adapters),
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
            return NativeBridgeEndpoint.uds(self._bridge, socket_path=self._socket_path)
        return NativeBridgeEndpoint.loopback(
            self._bridge,
            capabilities=self._capabilities,
            instance_id=self._instance_id,
            server_version=__version__,
        )

    def _listening(self) -> dict[str, object]:
        return listening_record(
            transport=self._options.transport, root=self._options.root,
            session_id=self._options.session_id, instance_id=self._instance_id,
            server_version=__version__, socket_path=self._socket_path,
            discovery_path=self._capabilities.endpoint_path)

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
        if self._ownership is not None:
            self._ownership.close()

    def run(self) -> int:
        endpoint = self._open()
        restore = install_signal_handlers(lambda: self.stop(endpoint))
        ownership_endpoint = str(
            self._socket_path if self._options.transport == "uds"
            else self._capabilities.endpoint_path)
        ownership_thread = start_ownership_monitor(
            self._ownership, transport=self._options.transport,
            endpoint=ownership_endpoint, stop=lambda: self.stop(endpoint))
        try:
            _emit(self._announce, self._listening())
            while not self._stopping.is_set():
                self.serve_one(endpoint)
        finally:
            restore()
            endpoint.close()
            self.close()
            if ownership_thread is not None:
                ownership_thread.join(timeout=1)
            _emit(
                self._announce,
                {
                    "event": "stopped",
                    "socket_exists": self._socket_path.exists(),
                    "discovery_exists": self._capabilities.endpoint_path.exists(),
                },
            )
        return 0

    def serve_one(self, endpoint: ServingEndpoint) -> None:
        """Serve one client, surviving anything that client can provoke.

        This is the process boundary: a refusal must end the connection, never
        the bridge the packaged application depends on.
        """
        try:
            endpoint.serve_once()
        except TimeoutError as exc:
            # A writer that outlives its connection is a teardown failure of
            # that connection, not of accept. It subclasses OSError, so it has
            # to be answered first: its message is the whole diagnostic, and
            # the listener's failure budget must not pay for stuck clients.
            self._connection_failed(exc)
            return
        except OSError as exc:
            if not self._stopping.is_set():
                self._absorb_socket_error(exc)
            return
        except Exception as exc:  # noqa: BLE001 - service boundary
            self._connection_failed(exc)
            return
        self._accept_failures = 0

    def _connection_failed(self, exc: BaseException) -> None:
        if self._stopping.is_set():
            return
        _emit(self._announce, connection_failure(exc))

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
        _emit(
            self._announce,
            {
                "event": "accept_failed",
                "error": f"OSError({exc.errno}): {exc.strerror}"[:200],
                "consecutive_failures": self._accept_failures,
            },
        )


def serve_bridge(
    options: NativeServeOptions,
    *,
    announce: Announce = _write_line,
) -> int:
    """Serve the authenticated local bridge until the process is stopped."""
    return BridgeProcess(options, announce).run()


@final
class _NativeServeArguments(argparse.Namespace):
    def __init__(self) -> None:
        super().__init__()
        self.transport: str | None = None
        self.session_id: str | None = None
        self.root: Path | None = None


def main(argv: list[str] | None = None) -> int:
    """Serve the bridge directly, for use as ``python -m birkin.native.serve``."""
    parser = argparse.ArgumentParser(prog="python -m birkin.native.serve")
    _ = parser.add_argument("--transport", choices=("uds", "loopback"))
    _ = parser.add_argument("--session-id")
    _ = parser.add_argument("--root", type=Path)
    arguments = parser.parse_args(argv, namespace=_NativeServeArguments())
    return serve_bridge(
        NativeServeOptions.resolve(
            transport=arguments.transport,
            session_id=arguments.session_id,
            root=arguments.root,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
