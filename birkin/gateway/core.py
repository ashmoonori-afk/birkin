"""Gateway control plane: session-per-conversation routing over channels."""

from __future__ import annotations

import threading
import time
from typing import Any

from .. import config, persona, prompts, store
from ..claude_session import ClaudeStreamSession
from ..runtime import ConfigError, Session, build_session


class Gateway:
    def __init__(self, cfg: dict[str, Any]):
        # The gateway may use its own (faster) model without affecting the REPL
        # or the nightly routine: config "gateway_model" overrides "model" for
        # this service only.
        gw_model = cfg.get("gateway_model")
        if gw_model:
            cfg = {**cfg, "model": gw_model}
        # SECURITY: the gateway is reachable over channels, so a chat message must
        # never reach a Claude process running with --dangerously-skip-permissions.
        # Force the safe access level here regardless of the global config.
        if cfg.get("cli_access") == "full":
            print("[gateway] cli_access 'full' is unsafe for a reachable service "
                  "— using 'workspace' for the gateway.", flush=True)
            cfg = {**cfg, "cli_access": "workspace"}
        self.cfg = cfg
        self.session: Session = build_session(cfg)  # may raise ConfigError
        self._chats: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._lock = threading.Lock()

        # Persistent (warm) Claude Code processes — one per conversation — for
        # the claude-cli provider. Pays cold-start once; warm replies are fast.
        self._persistent = (bool(cfg.get("gateway_persistent", True))
                            and cfg.get("provider") == "claude-cli")
        self._claude_sessions: dict[tuple[str, str], ClaudeStreamSession] = {}

    def _system_prompt(self) -> str:
        """birkin persona + memory + skill index, snapshot for a warm session."""
        sysp = prompts.build_cli_system(
            memory_block=self.session.memory.render(),
            persona=persona.read_soul())
        try:
            idx = self.session.skills.index()
        except Exception:
            idx = ""
        if idx:
            sysp += ("\n\n## birkin skills available\n"
                     "Read the referenced SKILL.md with your own file tools to "
                     "follow one when it fits the task.\n" + idx)
        return sysp

    def _claude_session(self, key: tuple[str, str]) -> ClaudeStreamSession:
        sess = self._claude_sessions.get(key)
        if sess is None:
            # Tools the headless gateway may use without a permission prompt
            # (e.g. company MCP servers). Empty -> rely on Claude Code settings.
            allowed = [str(t) for t in self.cfg.get("gateway_allowed_tools", []) if t]
            extra = ["--allowedTools", ",".join(allowed)] if allowed else None
            sess = ClaudeStreamSession(
                model=self.cfg.get("model"),
                cli_access=self.cfg.get("cli_access", "workspace"),
                append_system_prompt=self._system_prompt(),
                extra_args=extra)
            self._claude_sessions[key] = sess
        return sess

    def shutdown(self) -> None:
        for sess in self._claude_sessions.values():
            sess.close()
        self._claude_sessions.clear()

    def handle(self, channel: str, chat_id: str, text: str) -> str:
        """Route one inbound message to the agent and return the reply.

        Each (channel, chat_id) keeps its own conversation history; memory and
        skills are shared, so knowledge carries across channels.
        """
        text = (text or "").strip()
        if not text:
            return ""
        key = (channel, str(chat_id))
        # The global lock guards only the shared bookkeeping (the _claude_sessions
        # / _chats dicts and the single shared self.session). The actual LLM turn
        # runs OUTSIDE it: a persistent ClaudeStreamSession has its own per-session
        # lock, so independent conversations are not serialized behind each other.
        with self._lock:
            if text in ("/new", "/reset"):
                # Pop (not just reset) so a racing in-flight turn keeps its own
                # object and the NEXT turn builds a clean session.
                if self._persistent:
                    old = self._claude_sessions.pop(key, None)
                    if old is not None:
                        old.close()
                self._chats[key] = []
                return "Started a new conversation."
            sess = self._claude_session(key) if self._persistent else None

        print(f"[gateway] {channel}:{chat_id} « {text[:80]}", flush=True)
        t0 = time.monotonic()
        try:
            if self._persistent:
                # Warm Claude Code process keeps its own conversation context,
                # so only the new turn is sent.
                reply = sess.ask(text)
            else:
                # The non-persistent path shares the single self.session, so its
                # history swap must stay serialized under the global lock.
                with self._lock:
                    self.session.agent.messages = self._chats.get(key, [])
                    try:
                        reply = self.session.ask(text)
                    finally:
                        self._chats[key] = self.session.agent.messages
        except Exception as exc:
            dt = time.monotonic() - t0
            print(f"[gateway] {channel}:{chat_id} ✗ error after {dt:.1f}s: {exc}",
                  flush=True)
            return f"[error] {exc}"
        dt = time.monotonic() - t0
        print(f"[gateway] {channel}:{chat_id} » {len(reply or '')} chars in {dt:.1f}s",
              flush=True)
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

    mode = "warm/persistent" if gateway._persistent else "per-message"
    print(f"birkin gateway up · model {gateway.cfg.get('model')} · {mode} · "
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
    finally:
        gateway.shutdown()
    return 0
