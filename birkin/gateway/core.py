"""Gateway control plane: session-per-conversation routing over channels."""

from __future__ import annotations

import threading
from typing import Any

from .. import config, store
from ..runtime import ConfigError, Session, build_session


class Gateway:
    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.session: Session = build_session(cfg)  # may raise ConfigError
        self._chats: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def handle(self, channel: str, chat_id: str, text: str) -> str:
        """Route one inbound message to the agent and return the reply.

        Each (channel, chat_id) keeps its own conversation history; memory and
        skills are shared, so knowledge carries across channels.
        """
        text = (text or "").strip()
        if not text:
            return ""
        key = (channel, str(chat_id))
        with self._lock:
            if text in ("/new", "/reset"):
                self._chats[key] = []
                return "Started a new conversation."
            self.session.agent.messages = self._chats.get(key, [])
            try:
                reply = self.session.ask(text)
            except Exception as exc:
                return f"[error] {exc}"
            finally:
                self._chats[key] = self.session.agent.messages
            store.append_activity(f"gateway[{channel}:{chat_id}]: {text[:100]}")
            return reply or "(no reply)"


def run() -> int:
    cfg = config.load_config()
    try:
        gateway = Gateway(cfg)
    except ConfigError as exc:
        print(f"{exc}")
        return 1

    from .channels import build_channels
    channels = build_channels(cfg)
    if not channels:
        print("No channels enabled. Enable one in config.channels "
              "(http is on by default) and retry.")
        return 1

    print(f"birkin gateway up · model {cfg.get('model')} · "
          f"channels: {', '.join(c.name for c in channels)}")
    threads = []
    for ch in channels:
        t = threading.Thread(target=ch.start, args=(gateway,), daemon=True)
        t.start()
        threads.append(t)
    try:
        while any(t.is_alive() for t in threads):
            for t in threads:
                t.join(timeout=0.5)
    except KeyboardInterrupt:
        print("\ngateway stopping…")
    return 0
