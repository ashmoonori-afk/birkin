"""Telegram channel via long polling (standard library only).

Uses the Telegram Bot API over HTTPS with ``urllib`` — no third-party SDK.
Enable in config:

    "channels": {"telegram": {"enabled": true, "token": "<bot token>"}}

Create a bot and get the token from @BotFather.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING, Any

from .base import Channel

if TYPE_CHECKING:
    from ..core import Gateway

_API = "https://api.telegram.org/bot{token}/{method}"


def verify_token(token: str) -> tuple[bool, str]:
    """Check a bot token via getMe. Returns (ok, bot_username_or_error)."""
    if not token:
        return False, "empty token"
    url = _API.format(token=token, method="getMe")
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:
        return False, str(exc)
    if not data.get("ok"):
        return False, str(data.get("description", "invalid token"))
    return True, data.get("result", {}).get("username", "?")


class TelegramChannel(Channel):
    name = "telegram"

    def __init__(self, token: str):
        self.token = token

    def _call(self, method: str, params: dict[str, Any], timeout: int = 60) -> dict[str, Any]:
        url = _API.format(token=self.token, method=method)
        data = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))

    def start(self, gateway: "Gateway") -> None:
        print("  · telegram channel polling for updates")
        offset = 0
        while True:
            try:
                res = self._call("getUpdates", {"offset": offset, "timeout": 50}, timeout=60)
            except Exception as exc:
                print(f"[telegram] poll error: {exc}")
                time.sleep(5)
                continue
            for upd in res.get("result", []):
                offset = max(offset, upd.get("update_id", 0) + 1)
                msg = upd.get("message") or {}
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = msg.get("text", "")
                if not (chat_id and text):
                    continue
                reply = gateway.handle("telegram", chat_id, text)
                try:
                    self._call("sendMessage", {"chat_id": chat_id, "text": reply[:4000]})
                except Exception as exc:
                    print(f"[telegram] send error: {exc}")
