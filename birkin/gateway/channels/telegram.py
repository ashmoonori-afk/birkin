"""Telegram channel via long polling (standard library only).

Uses the Telegram Bot API over HTTPS with ``urllib`` — no third-party SDK.
Enable in config:

    "channels": {"telegram": {"enabled": true, "token": "<bot token>"}}

Create a bot and get the token from @BotFather.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
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

    def __init__(self, token: str, allowed_chat_ids: list[str] | None = None):
        self.token = token
        # When non-empty, only these chat ids may drive the agent (access control
        # for a reachable bot). Empty -> open (a startup warning is printed).
        self.allowed_chat_ids = set(allowed_chat_ids or [])

    def _call(self, method: str, params: dict[str, Any], timeout: int = 60) -> dict[str, Any]:
        url = _API.format(token=self.token, method=method)
        data = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))

    def _keep_typing(self, chat_id: str, stop: threading.Event) -> None:
        """Show a 'typing…' indicator until ``stop`` is set.

        Replies can take many seconds (the CLI backend spawns a full agent), so
        without this the user stares at silence and assumes it's dead. Telegram
        clears the indicator after ~5s, so we re-send it every few seconds.
        """
        while not stop.is_set():
            try:
                self._call("sendChatAction",
                           {"chat_id": chat_id, "action": "typing"}, timeout=15)
            except (OSError, urllib.error.URLError, ValueError):
                pass  # cosmetic — ignore transient network errors
            except Exception as exc:
                print(f"[telegram] typing error: {exc}")
                return
            stop.wait(4.0)

    def start(self, gateway: "Gateway") -> None:
        print("  · telegram channel polling for updates")
        # Register the command menu so typing "/" shows them in the Telegram UI.
        try:
            from ..core import command_menu
            self._call("setMyCommands",
                       {"commands": json.dumps(command_menu())})
        except Exception as exc:
            print(f"[telegram] setMyCommands failed: {exc}")
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
                if self.allowed_chat_ids and chat_id not in self.allowed_chat_ids:
                    print(f"[telegram] ignoring message from unauthorized chat {chat_id}")
                    continue
                stop = threading.Event()
                pinger = threading.Thread(target=self._keep_typing,
                                          args=(chat_id, stop), daemon=True)
                pinger.start()
                try:
                    reply = gateway.handle("telegram", chat_id, text)
                finally:
                    stop.set()
                    pinger.join(timeout=16)
                try:
                    self._call("sendMessage", {"chat_id": chat_id, "text": reply[:4000]})
                except Exception as exc:
                    print(f"[telegram] send error: {exc}")
                if gateway.pending_hard_restart:
                    # Confirm this update to Telegram BEFORE re-exec, so the new
                    # process doesn't re-receive /hard-restart and loop forever.
                    try:
                        self._call("getUpdates", {"offset": offset, "timeout": 0})
                    except Exception:
                        pass
                    gateway.do_hard_restart()  # replaces the process; never returns
