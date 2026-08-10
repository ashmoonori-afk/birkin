"""Typed client for the local Birkin Gateway."""

from __future__ import annotations

import json
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPException
from urllib.parse import urlsplit


class GatewayVoiceError(RuntimeError):
    """The local Gateway rejected or malformed a voice request."""


@dataclass(frozen=True)
class GatewayClient:
    """Submit voice text through the existing local HTTP channel."""

    url: str
    session_id: str
    token: str = ""
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        endpoint = urlsplit(self.url)
        if (
            endpoint.scheme != "http"
            or endpoint.hostname not in {"127.0.0.1", "::1", "localhost"}
            or endpoint.path != "/message"
            or endpoint.username is not None
            or endpoint.password is not None
            or endpoint.query
            or endpoint.fragment
        ):
            raise ValueError(
                "voice Gateway URL must be a loopback HTTP /message endpoint"
            )
        try:
            _ = endpoint.port
        except ValueError as exc:
            raise ValueError("voice Gateway URL has an invalid port") from exc

    def send(self, text: str) -> str:
        command = text.strip()
        if not command:
            raise ValueError("voice command must not be empty")

        body = json.dumps(
            {
                "channel": "voice",
                "session": self.session_id,
                "text": command,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["X-Birkin-Token"] = self.token
        endpoint = urlsplit(self.url)
        host = endpoint.hostname
        if host is None:
            raise GatewayVoiceError("Gateway URL is missing a host")
        connection = HTTPConnection(
            host,
            endpoint.port or 80,
            timeout=self.timeout_seconds,
        )
        try:
            connection.request("POST", endpoint.path, body=body, headers=headers)
            response = connection.getresponse()
            if response.status >= 400:
                raise GatewayVoiceError(
                    f"Gateway returned HTTP {response.status}"
                )
            payload = json.loads(response.read().decode("utf-8"))
        except GatewayVoiceError:
            raise
        except (HTTPException, OSError, TimeoutError, json.JSONDecodeError) as exc:
            raise GatewayVoiceError(str(exc)) from exc
        finally:
            connection.close()

        if not isinstance(payload, dict):
            raise GatewayVoiceError("Gateway response must be a JSON object")
        reply = payload.get("reply")
        if not isinstance(reply, str):
            raise GatewayVoiceError("Gateway response is missing reply text")
        return reply
