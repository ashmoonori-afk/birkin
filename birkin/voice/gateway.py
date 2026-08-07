"""Typed client for the local Birkin Gateway."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class GatewayVoiceError(RuntimeError):
    """The local Gateway rejected or malformed a voice request."""


@dataclass(frozen=True)
class GatewayClient:
    """Submit voice text through the existing local HTTP channel."""

    url: str
    session_id: str
    token: str = ""
    timeout_seconds: float = 30.0

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
        request = Request(
            self.url,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise GatewayVoiceError(str(exc)) from exc

        if not isinstance(payload, dict):
            raise GatewayVoiceError("Gateway response must be a JSON object")
        reply = payload.get("reply")
        if not isinstance(reply, str):
            raise GatewayVoiceError("Gateway response is missing reply text")
        return reply
