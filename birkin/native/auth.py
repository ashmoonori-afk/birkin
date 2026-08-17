"""Connection-local authentication for the native bridge."""

from __future__ import annotations

import secrets
from typing import final

from birkin.native.capability import (
    BootstrapSecretStore,
    CapabilityScope,
    SessionCapability,
)
from birkin.native.protocol import (
    NATIVE_PROTOCOL_VERSION,
    JSONValue,
    NativeEnvelope,
    NativeProtocolError,
)
from birkin.native.transport import NativeConnection


@final
class NativeConnectionAuth:
    def __init__(
        self,
        capabilities: BootstrapSecretStore,
        *,
        instance_id: str,
    ) -> None:
        self._capabilities = capabilities
        self._instance_id = instance_id

    def authenticate_hello(
        self,
        hello: NativeEnvelope,
        *,
        connection: NativeConnection,
        transport: str,
        connection_id: str,
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
        scope = CapabilityScope(
            instance_id=self._instance_id,
            connection_id=connection_id,
            surface=_string(hello.body, "surface"),
            view_id=_string(hello.body, "view_id"),
        )
        if transport == "uds":
            if connection.peer_uid is None or bootstrap is not None:
                raise NativeProtocolError(
                    "E_PEER_UID_MISMATCH",
                    "Unix socket hello requires same-user peer credentials",
                )
            return self._capabilities.mint_session(scope=scope)
        if transport == "loopback" and isinstance(bootstrap, str):
            return self._capabilities.exchange(bootstrap, scope=scope)
        raise NativeProtocolError(
            "E_BOOTSTRAP_INVALID",
            "loopback hello requires a bootstrap secret",
        )

    def require_capability(
        self,
        body: dict[str, JSONValue],
        capability: SessionCapability,
    ) -> None:
        token = body.get("session_capability")
        if (
            not isinstance(token, str)
            or not secrets.compare_digest(token, capability.token)
            or not self._capabilities.authenticate_session(
                token,
                scope=capability.scope,
            )
        ):
            raise NativeProtocolError(
                "E_CAPABILITY_INVALID",
                "native session capability is invalid",
            )


def _string(body: dict[str, JSONValue], key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str):
        raise NativeProtocolError("E_BODY", f"{key} must be a string")
    return value
