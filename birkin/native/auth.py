"""Connection-local authentication for the native bridge."""

from __future__ import annotations

import secrets
from typing import final

from birkin.native.capability import BootstrapSecretStore, SessionCapability
from birkin.native.protocol import (
    NATIVE_PROTOCOL_VERSION,
    JSONValue,
    NativeEnvelope,
    NativeProtocolError,
)
from birkin.native.transport import NativeConnection


@final
class NativeConnectionAuth:
    def __init__(self, capabilities: BootstrapSecretStore) -> None:
        self._capabilities = capabilities

    def authenticate_hello(
        self,
        hello: NativeEnvelope,
        *,
        connection: NativeConnection,
        transport: str,
    ) -> SessionCapability:
        versions = hello.body["supported_protocol_versions"]
        if (
            not isinstance(versions, list)
            or NATIVE_PROTOCOL_VERSION not in versions
        ):
            raise NativeProtocolError(
                "E_PROTOCOL_VERSION",
                "client and server share no native protocol version",
            )
        bootstrap = hello.body["bootstrap_secret"]
        if transport == "uds":
            if connection.peer_uid is None or bootstrap is not None:
                raise NativeProtocolError(
                    "E_PEER_UID_MISMATCH",
                    "Unix socket hello requires same-user peer credentials",
                )
            return self._capabilities.mint_session()
        if transport == "loopback" and isinstance(bootstrap, str):
            return self._capabilities.exchange(bootstrap)
        raise NativeProtocolError(
            "E_BOOTSTRAP_INVALID",
            "loopback hello requires a bootstrap secret",
        )

    def require_capability(
        self,
        body: dict[str, JSONValue],
        active_token: str,
    ) -> None:
        token = body.get("session_capability")
        if (
            not isinstance(token, str)
            or not secrets.compare_digest(token, active_token)
            or not self._capabilities.authenticate_session(token)
        ):
            raise NativeProtocolError(
                "E_CAPABILITY_INVALID",
                "native session capability is invalid",
            )
