"""Production listener, discovery record, and bridge accept lifecycle."""

from __future__ import annotations

import os
from pathlib import Path
from types import TracebackType
from typing import final

from birkin import store
from birkin.native.capability import BootstrapSecretStore
from birkin.native.server import NativeBridgeServer
from birkin.native.transport import NativeListener


@final
class NativeBridgeEndpoint:
    def __init__(
        self,
        bridge: NativeBridgeServer,
        listener: NativeListener,
        *,
        capabilities: BootstrapSecretStore | None,
        expected_uid: int | None,
    ) -> None:
        self._bridge = bridge
        self._listener = listener
        self._capabilities = capabilities
        self._expected_uid = expected_uid
        self._closed = False

    @classmethod
    def uds(
        cls,
        bridge: NativeBridgeServer,
        *,
        socket_path: Path,
    ) -> NativeBridgeEndpoint:
        geteuid = getattr(os, "geteuid", None)
        if not callable(geteuid):
            raise OSError("Unix peer credentials are unavailable")
        expected_uid = geteuid()
        if not isinstance(expected_uid, int):
            raise OSError("Unix peer credentials are invalid")
        lock_path = socket_path.with_suffix(".bind.lock")
        with store.file_lock(lock_path):
            listener = NativeListener.uds(socket_path)
        return cls(
            bridge,
            listener,
            capabilities=None,
            expected_uid=expected_uid,
        )

    @classmethod
    def loopback(
        cls,
        bridge: NativeBridgeServer,
        *,
        capabilities: BootstrapSecretStore,
        instance_id: str,
        server_version: str,
    ) -> NativeBridgeEndpoint:
        listener = NativeListener.loopback()
        host, port = listener.address
        try:
            _ = capabilities.publish_loopback(
                host=host,
                port=port,
                instance_id=instance_id,
                server_version=server_version,
            )
        except BaseException:
            listener.close()
            raise
        return cls(
            bridge,
            listener,
            capabilities=capabilities,
            expected_uid=None,
        )

    @property
    def address(self) -> tuple[str, int]:
        return self._listener.address

    def serve_once(self) -> None:
        connection = self._listener.accept(
            expected_uid=self._expected_uid,
        )
        self._bridge.serve_connection(
            connection,
            transport=self._listener.transport,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._listener.close()
        if self._capabilities is not None:
            self._capabilities.revoke_all_sessions()
            self._capabilities.endpoint_path.unlink(missing_ok=True)

    def __enter__(self) -> NativeBridgeEndpoint:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
