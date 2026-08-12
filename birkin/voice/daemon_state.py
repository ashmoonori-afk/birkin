"""Authenticated local state and client protocol for the voice daemon."""

from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass

_MAX_MESSAGE = 4096
_CONTROL_TIMEOUT_SECONDS = 2.0
_STOP_RESPONSE_TIMEOUT_SECONDS = 32.0


@dataclass(frozen=True, slots=True)
class DaemonState:
    instance_id: str
    token: str
    pid: int
    host: str
    port: int
    status: str = "running"

    @classmethod
    def from_mapping(cls, value: object) -> DaemonState:
        if not isinstance(value, dict):
            raise TypeError("voice daemon state must be an object")
        instance_id = value.get("instance_id")
        token = value.get("token")
        pid = value.get("pid")
        host = value.get("host")
        port = value.get("port")
        status = value.get("status", "running")
        if not isinstance(instance_id, str) or not instance_id:
            raise ValueError("voice daemon instance_id must be text")
        if not isinstance(token, str) or not token:
            raise ValueError("voice daemon token must be text")
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            raise ValueError("voice daemon pid must be positive")
        if host != "127.0.0.1":
            raise ValueError("voice daemon host must be loopback")
        if not isinstance(port, int) or isinstance(port, bool):
            raise TypeError("voice daemon port must be an integer")
        if not 1 <= port <= 65535:
            raise ValueError("voice daemon port is out of range")
        if status not in {"running", "stopping"}:
            raise ValueError("voice daemon status is invalid")
        return cls(instance_id, token, pid, host, port, status)


def create_control_listener() -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name == "nt":
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            listener.setsockopt(socket.SOL_SOCKET, exclusive, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    return listener


def request(state: DaemonState, action: str) -> str:
    payload = {
        "action": action,
        "instance_id": state.instance_id,
        "token": state.token,
    }
    with socket.create_connection(
        (state.host, state.port),
        timeout=_CONTROL_TIMEOUT_SECONDS,
    ) as client:
        client.settimeout(
            _STOP_RESPONSE_TIMEOUT_SECONDS
            if action == "STOP"
            else _CONTROL_TIMEOUT_SECONDS
        )
        client.sendall(json.dumps(payload).encode("utf-8") + b"\n")
        response = client.makefile("rb").readline(_MAX_MESSAGE + 1)
    if not response or len(response) > _MAX_MESSAGE:
        raise OSError("invalid voice daemon response")
    decoded = json.loads(response)
    if not isinstance(decoded, dict) or not isinstance(
        decoded.get("status"),
        str,
    ):
        raise OSError("invalid voice daemon response")
    return decoded["status"]
