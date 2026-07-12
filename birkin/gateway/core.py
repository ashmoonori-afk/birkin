"""Gateway control plane: session-per-conversation routing over channels."""

from __future__ import annotations

import threading
import time
from typing import Any

from .. import config, pools, promptgate, security, store
from ..claude_session import ClaudeStreamSession
from ..runtime import ConfigError, Session, build_session

# Gateway chat commands. Each: (canonical name, description, {accepted triggers}).
# Triggers include hyphen / underscore / run-together variants because Telegram
# bot commands only allow [a-z0-9_] (no hyphen), while users still type hyphens.
_GATEWAY_COMMANDS: list[tuple[str, str, set[str]]] = [
    ("help", "Show these commands",
     {"help", "commands", "start", "menu", "?"}),
    ("new", "Start a fresh conversation (clear history)",
     {"new", "reset"}),
    ("restart", "Soft restart — reload config/persona/memory, clear sessions",
     {"restart", "restart-gateway", "restart_gateway", "restartgateway",
      "reload"}),
    ("hard_restart", "Hard restart — re-exec the gateway (picks up code changes)",
     {"hard-restart", "hard_restart", "hardrestart", "restart-hard",
      "restart_hard", "restarthard"}),
    ("neurosis", "Deep interview — clarify a vague idea before acting",
     {"neurosis", "interview"}),
    ("models", "List or select the gateway model (auto-restarts to apply)",
     {"models", "model"}),
    ("update", "Remote update — pull new code from the repo, then auto restart",
     {"update", "upgrade", "pull"}),
]

# Friendly short model names accepted by `claude --model` (full claude-… IDs also OK).
_GATEWAY_MODELS = ["opus", "sonnet", "haiku"]            # claude-cli suggestions
_CODEX_GATEWAY_MODELS = ["gpt-5", "gpt-5-codex", "o3", "codex"]  # codex-cli (codex validates -m)
# Commands that pull code / restart the service / rewrite config — gated to
# trusted channels only (see Gateway._command_trusted).
_PRIVILEGED_COMMANDS = {"update", "models", "restart", "hard_restart"}
# Providers with a warm persistent-session implementation (see
# claude_session.ClaudeStreamSession / codex_session.CodexAppServerSession).
_PERSISTENT_PROVIDERS = ("claude-cli", "codex-cli")


def _gateway_model_choices(provider: str) -> tuple[list[str], str]:
    """Suggested gateway models + an 'other IDs' hint, per provider."""
    if provider == "codex-cli":
        return _CODEX_GATEWAY_MODELS, "또는 codex가 지원하는 -m 모델 ID"
    if provider == "claude-cli":
        return _GATEWAY_MODELS, "또는 claude-… 전체 ID"
    return [], "provider가 지원하는 모델 ID"


def _gateway_model_accepted(provider: str, name: str, known: list[str]) -> bool:
    """claude-cli is validated against the known set; other providers pass the
    model id straight through (codex / the API validate it themselves)."""
    if not name:
        return False
    if provider == "claude-cli":
        return name in known or name.startswith("claude-")
    return True


def match_command(text: str) -> tuple[str | None, str]:
    """Map an inbound message to (canonical command, remaining arg).

    Tolerates a leading ``/``, a ``@botname`` suffix, hyphen/underscore variants,
    and a trailing arg. ``/restart … hard`` (or ``--hard``) maps to hard_restart.
    Returns ``(None, "")`` when the text is not a recognised command.
    """
    t = (text or "").strip()
    if not t.startswith("/"):
        return None, ""
    toks = t[1:].split(maxsplit=1)
    if not toks:
        return None, ""
    name = toks[0].split("@", 1)[0].strip().lower()
    rest = toks[1].strip() if len(toks) > 1 else ""
    for canonical, _desc, triggers in _GATEWAY_COMMANDS:
        if name in triggers:
            if canonical == "restart" and rest.strip().lower() in ("hard", "--hard"):
                return "hard_restart", ""  # hard_restart takes no arg
            return canonical, rest
    return None, ""


def gateway_help_text() -> str:
    lines = ["🤖 birkin gateway — commands:"]
    for canonical, desc, _ in _GATEWAY_COMMANDS:
        lines.append(f"/{canonical} — {desc}")
    return "\n".join(lines)


def command_menu() -> list[dict[str, str]]:
    """Payload for Telegram setMyCommands (canonical, [a-z0-9_] names only)."""
    return [{"command": c, "description": d} for c, d, _ in _GATEWAY_COMMANDS]


# Shared friendly tail so soft + hard restart greet the same way.
_BACK_GREETING = "다시 왔습니다 👋 무엇을 도와드릴까요?"
# Sent by the re-exec'd process after a HARD restart (code + config reloaded).
_RESTART_GREETING = "✅ 재시작 완료! 코드·설정을 새로 반영했어요. " + _BACK_GREETING


def _restart_marker_path():
    """One-shot marker dropped before a hard re-exec so the new process can greet
    the chat that asked for the restart."""
    from .. import config
    return config.birkin_home() / "restart_notice.json"


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

        # Persistent (warm) CLI processes — one per conversation — for the
        # claude-cli (stream-json) and codex-cli (app-server) providers.
        # Pays cold-start once; warm replies are ~model-time.
        self._persistent = (bool(cfg.get("gateway_persistent", True))
                            and cfg.get("provider") in _PERSISTENT_PROVIDERS)
        # Pool with idle-TTL + LRU cap: dead chats stop holding a live claude
        # process (daemon resource layer; docs/hermes-comparison.md §4).
        self._claude_sessions = pools.SessionPool(
            self._new_claude_session,
            max_sessions=int(cfg.get("gateway_max_sessions", 8) or 8),
            idle_ttl=float(cfg.get("gateway_session_ttl_s", 3600) or 3600))
        # Pre-warmed spare session (fungible; adopted by the next new
        # conversation) — see _new_claude_session / _make_spare.
        self._spare: ClaudeStreamSession | None = None
        self._spare_lock = threading.Lock()
        # Set by a /hard-restart command; the channel re-execs after replying.
        self._hard_restart = False
        # (channel, chat_id) that triggered a hard restart — persisted across the
        # re-exec so the new process can greet that chat that it is back up.
        self._restart_origin: tuple[str, str] | None = None
        # Loaded by run() from the restart marker after a re-exec (one-shot).
        self._restart_notice: dict[str, Any] | None = None

    def _system_prompt(self) -> str:
        """birkin persona + memory + skill index, snapshot for a warm session.
        Composed through the Prompt-Gate (promptgate) like every other surface."""
        try:
            idx = self.session.skills.index()
        except Exception:
            idx = ""
        extra = ("\n\n## birkin skills available\n"
                 "Read the referenced SKILL.md with your own file tools to "
                 "follow one when it fits the task.\n" + idx) if idx else ""
        return promptgate.compose_cli(
            self.cfg, memory_block=self.session.memory.render(), extra=extra)

    def _new_claude_session(self, key: tuple[str, str]) -> ClaudeStreamSession:
        """SessionPool factory: one warm session per conversation key.

        A pre-warmed spare (see :meth:`prewarm`) is adopted first: gateway
        sessions are configured identically, so the spare is fungible and the
        first message of a new conversation skips the ~28 s cold start.
        """
        with self._spare_lock:
            spare, self._spare = self._spare, None
        if spare is not None and spare.is_alive():
            # replace the spare in the background for the NEXT new conversation
            threading.Thread(target=self._make_spare, daemon=True).start()
            return spare
        return self._build_claude_session()

    def _build_claude_session(self):
        """Warm session for the configured provider (claude or codex)."""
        if self.cfg.get("provider") == "codex-cli":
            from ..codex_session import CodexAppServerSession
            return CodexAppServerSession(
                model=self.cfg.get("model"),
                preamble=self._system_prompt())
        # Tools the headless gateway may use without a permission prompt
        # (e.g. company MCP servers). Empty -> rely on Claude Code settings.
        allowed = [str(t) for t in self.cfg.get("gateway_allowed_tools", []) if t]
        extra = ["--allowedTools", ",".join(allowed)] if allowed else None
        # Headless children run with the user's interactive hook stack
        # DISABLED and a bounded thinking budget — measured at 3-6 s/turn of
        # hooks + 2.8 s TTFT of default thinking (hermes-comparison.md §6).
        settings = ({"disableAllHooks": True}
                    if self.cfg.get("gateway_clean_hooks", True) else None)
        env_extra = {"MAX_THINKING_TOKENS":
                     str(int(self.cfg.get("gateway_thinking_tokens", 0) or 0))}
        return ClaudeStreamSession(
            model=self.cfg.get("model"),
            cli_access=self.cfg.get("cli_access", "workspace"),
            append_system_prompt=self._system_prompt(),
            extra_args=extra, settings=settings, env_extra=env_extra)

    def _make_spare(self) -> None:
        """Spawn one warm, unclaimed session so the next new conversation
        skips the CLI cold start. Never raises (best-effort warm-up)."""
        if not self._persistent or not self.cfg.get("gateway_prewarm", True):
            return
        try:
            s = self._build_claude_session()
            s.start()
        except Exception as exc:              # warm-up must never take the
            print(f"[gateway] prewarm failed: {exc}", flush=True)  # service down
            return
        with self._spare_lock:
            if self._spare is None:
                self._spare = s
                return
        s.close()   # raced another warm-up; don't leak the extra process

    def prewarm(self) -> None:
        """Public entry: warm the first spare in the background at boot."""
        threading.Thread(target=self._make_spare, daemon=True).start()

    def _claude_session(self, key: tuple[str, str]) -> ClaudeStreamSession:
        return self._claude_sessions.get(key)

    def shutdown(self) -> None:
        self._claude_sessions.clear()   # the pool closes every session
        with self._spare_lock:
            spare, self._spare = self._spare, None
        if spare is not None:
            spare.close()

    def restart(self) -> str:
        """Soft-restart the gateway in place (channels stay up).

        Reloads config + persona + memory + skills + MCP allow-list and tears
        down every warm Claude session, so the next message reflects current
        settings. Conversations start fresh. The process is NOT killed, so code
        changes still require restarting `birkin gateway`. Callers hold the lock.
        """
        assert self._lock.locked(), "restart() must be called holding self._lock"
        self._claude_sessions.clear()   # the pool closes every session
        self._chats.clear()
        # The pre-warmed spare carries a PRE-restart persona/config snapshot —
        # discard it (mirror shutdown()) or the next new conversation would
        # silently adopt stale state, contradicting this method's promise.
        with self._spare_lock:
            spare, self._spare = self._spare, None
        if spare is not None:
            spare.close()
        cfg = config.load_config()
        if cfg.get("gateway_model"):
            cfg = {**cfg, "model": cfg["gateway_model"]}
        if cfg.get("cli_access") == "full":
            cfg = {**cfg, "cli_access": "workspace"}
        self.cfg = cfg
        self._persistent = (bool(cfg.get("gateway_persistent", True))
                            and cfg.get("provider") in _PERSISTENT_PROVIDERS)
        try:
            self.session = build_session(cfg)
        except ConfigError as exc:
            return f"[restart] config error: {exc}"
        self.prewarm()   # rebuild the spare from the RELOADED config
        return ("♻️ Gateway restarted — reloaded config, persona, memory and "
                "skills; warm sessions cleared (conversations start fresh).\n\n"
                + _BACK_GREETING)

    @property
    def pending_hard_restart(self) -> bool:
        return self._hard_restart

    def do_hard_restart(self) -> None:
        """Re-execute the gateway process (picks up CODE changes too).

        Replaces the current process image, so this never returns. Warm Claude
        subprocesses are terminated first to avoid orphans. Called by a channel
        AFTER it has delivered the reply (and, for Telegram, acknowledged the
        update so the /hard-restart message is not redelivered into a loop).
        """
        import os
        import sys
        if self._restart_origin:   # leave a one-shot note so we can greet on boot
            try:
                from .. import store
                store._write_json(_restart_marker_path(),
                                  {"channel": self._restart_origin[0],
                                   "chat_id": self._restart_origin[1]})
            except Exception:
                pass
        try:
            self.shutdown()
        except Exception:
            pass
        print("[gateway] hard restart: re-executing `birkin gateway`…", flush=True)
        os.execv(sys.executable, [sys.executable, "-m", "birkin", "gateway"])

    def take_restart_greeting(self, channel: str) -> str | None:
        """If this process just came back from a hard restart triggered on
        ``channel``, return that chat_id once (then forget it) so the channel can
        send a 'back online' greeting. Returns None otherwise."""
        n = self._restart_notice
        if isinstance(n, dict) and n.get("channel") == channel:
            self._restart_notice = None
            return str(n.get("chat_id"))
        return None

    def handle(self, channel: str, chat_id: str, text: str,
               on_text=None) -> str:
        """Route one inbound message to the agent and return the reply.

        ``on_text`` (optional) receives append-style reply pieces as they
        stream from the model, so a channel can show partial output (e.g.
        Telegram edit-streaming) instead of waiting for the full turn.
        Commands and the non-persistent path reply in one piece.

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
        cmd, cmd_arg = match_command(text)
        display_text = text
        if cmd == "neurosis":
            # Seed/resume the interview, then run the kickoff as a normal turn so
            # it works on both the persistent and non-persistent paths.
            from .. import neurosis
            resolution = None
            kept = []
            for tok in cmd_arg.split():
                if tok in ("--quick", "--standard", "--deep"):
                    resolution = tok[2:]
                else:
                    kept.append(tok)
            idea_arg = " ".join(kept)
            # The neurosis state file is shared mutable state reached from
            # multiple channel threads, and seed_or_resume is a read-modify-write
            # (same idea -> same slug -> same path). Serialize it under the global
            # lock so two concurrent /neurosis for one idea cannot clobber each
            # other; the cheap file I/O does not gate the LLM turn below.
            with self._lock:
                seed = neurosis.seed_or_resume(idea_arg, cfg=self.cfg,
                                               resolution=resolution)
            if seed is None:
                return ("아이디어를 함께 주세요: /neurosis <모호한 아이디어> "
                        "(진행 중인 인터뷰가 있으면 /neurosis 만으로 재개).")
            text = neurosis.start_prompt(seed)               # sent to the agent
            display_text = idea_arg or "/neurosis (resume)"  # logged / auto-saved
            cmd = None                                       # fall through to a turn
        with self._lock:
            # Privileged commands pull code / restart the service / rewrite config.
            # An OPEN Telegram bot (no allowed_chat_ids) must not let strangers
            # trigger them. (When allowed_chat_ids IS set, telegram.py already
            # dropped unauthorized chats before this point.)
            if cmd in _PRIVILEGED_COMMANDS and not self._command_trusted(channel):
                return ("This command is restricted. Set "
                        "channels.telegram.allowed_chat_ids so only you can run "
                        "/update, /models, /restart and /hard_restart.")
            if cmd == "help":
                return gateway_help_text()
            if cmd == "models":
                reply = self._models_command(cmd_arg)
                if self._hard_restart:   # /models scheduled a re-exec
                    self._restart_origin = (channel, str(chat_id))
                return reply
            if cmd == "hard_restart":
                # The receiving channel re-execs after it delivers this reply;
                # remember who asked so the new process can greet them.
                self._hard_restart = True
                self._restart_origin = (channel, str(chat_id))
                print(f"[gateway] HARD restart requested via {channel}:{chat_id}",
                      flush=True)
                return ("♻️ Hard restart — re-executing `birkin gateway` to pick up "
                        "code + config changes. Reconnecting in a moment…")
            if cmd == "update":
                # Pull new repo code (main code + bundled skills). User state in
                # ~/.birkin (config, memory, user skills) lives outside the repo
                # and is never touched. On a code change, re-exec like hard_restart.
                from .. import updater
                result = updater.update()
                if result.get("updated"):
                    self._hard_restart = True
                    self._restart_origin = (channel, str(chat_id))
                    print(f"[gateway] update pulled new code via "
                          f"{channel}:{chat_id}; scheduling hard restart", flush=True)
                    return (f"⬇️ {result['message']}\n"
                            "♻️ 새 코드를 반영하려고 재시작합니다…")
                return f"{'✅' if result.get('ok') else '⚠️'} {result['message']}"
            if cmd == "restart":
                print(f"[gateway] restart requested via {channel}:{chat_id}",
                      flush=True)
                return self.restart()
            if cmd == "new":
                # Pop (not just reset) so a racing in-flight turn keeps its own
                # object and the NEXT turn builds a clean session.
                if self._persistent:
                    old = self._claude_sessions.pop(key)
                    if old is not None:
                        old.close()
                self._chats[key] = []
                return "Started a new conversation."
            # Snapshot persistence + session together under the lock: a /restart
            # could flip self._persistent between here and the ask() below.
            persistent = self._persistent
            sess = self._claude_session(key) if persistent else None

        print(f"[gateway] {channel}:{chat_id} « {display_text[:80]}", flush=True)
        t0 = time.monotonic()
        try:
            if persistent:
                # Warm Claude Code process keeps its own conversation context,
                # so only the new turn is sent.
                reply = sess.ask(text, on_text=on_text)
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
        store.append_activity(f"gateway[{channel}:{chat_id}]: {display_text[:100]}")
        # Auto-save the turn so the nightly Morpheus routine can extract memory —
        # but ONLY for trusted conversations (an open Telegram bot's strangers
        # must not be persisted into long-term memory). Runs OUTSIDE the global
        # lock; transcripts.append_turn is per-conversation locked.
        if self._autosave_trusted(channel):
            from .. import transcripts
            transcripts.append_turn(channel, str(chat_id), display_text, reply or "",
                                    cfg=self.cfg)
        return reply or "(no reply)"

    def _models_command(self, arg: str) -> str:
        """List the gateway model, or select one and schedule a hard restart so the
        new model takes effect (the gateway's model is fixed at process start).
        Called under the lock."""
        name = (arg or "").strip().split()[0] if (arg or "").strip() else ""
        provider = self.cfg.get("provider", "")
        known, extra_hint = _gateway_model_choices(provider)
        listing = (", ".join(known) + " " if known else "") + f"({extra_hint})"
        example = known[0] if known else "<모델 ID>"
        if not name:
            return (f"현재 게이트웨이 모델: {self.cfg.get('model')} [{provider}]\n"
                    f"사용 가능: {listing}\n"
                    f"바꾸려면 /models <이름> — 고르면 적용을 위해 자동으로 재시작해요. "
                    f"예: /models {example}")
        if not _gateway_model_accepted(provider, name, known):
            return (f"'{name}'은(는) 모르는 모델이에요. 사용 가능: {listing}. "
                    f"예: /models {example}")
        cfg = config.load_config()
        cfg["gateway_model"] = name
        config.save_config(cfg)
        # Keep in-memory state consistent even if the scheduled re-exec never
        # happens (os.execv raises) — otherwise self.cfg would report the old
        # model. The live model only actually changes on the next process start.
        self.cfg = {**self.cfg, "gateway_model": name, "model": name}
        self._hard_restart = True  # the channel re-execs after sending this reply
        print(f"[gateway] model → {name}; scheduling hard restart", flush=True)
        return (f"✅ 게이트웨이 모델을 '{name}'로 바꿨어요. 적용하려고 지금 재시작합니다 "
                f"— 잠시 후 다시 말 걸어주세요.")

    def _autosave_trusted(self, channel: str) -> bool:
        """Whether turns from ``channel`` may be auto-saved + memorized.

        Telegram is trusted only when ``allowed_chat_ids`` is set — otherwise the
        bot is open and a stranger's messages would be persisted and could poison
        the vault. REPL and the loopback HTTP channel are local → trusted.
        """
        if channel == "telegram":
            tg = (self.cfg.get("channels", {}) or {}).get("telegram", {}) or {}
            return bool(tg.get("allowed_chat_ids"))
        return True

    def _command_trusted(self, channel: str) -> bool:
        """Whether privileged commands (update/models/restart/hard_restart) may
        run from ``channel``. Same trust rule as autosave: an open Telegram bot
        (no allowed_chat_ids) is untrusted; loopback HTTP and REPL are local."""
        return self._autosave_trusted(channel)


def run() -> int:
    cfg = config.load_config()
    # Advisory (never blocking): make native-loop tool exposure visible
    # before the gateway becomes reachable over a channel.
    security.print_gateway_warnings(cfg)
    try:
        gateway = Gateway(cfg)
    except ConfigError as exc:
        print(f"{exc}")
        return 1

    # Just came back from a hard re-exec? Load the one-shot marker so the channel
    # that triggered it greets that chat "I'm back". Delete it immediately.
    try:
        from .. import store
        marker = _restart_marker_path()
        notice = store._read_json(marker, None)
        if isinstance(notice, dict):
            gateway._restart_notice = notice
            try:
                marker.unlink()
            except OSError:
                pass
    except Exception:
        pass

    from .channels import build_channels
    channels = build_channels(cfg)
    if not channels:
        print("No channels enabled. Enable one in config.channels "
              "(http is on by default) and retry.")
        return 1

    mode = "warm/persistent" if gateway._persistent else "per-message"
    gateway.prewarm()   # first message of a new conversation skips cold start
    print(f"birkin gateway up · model {gateway.cfg.get('model')} · {mode} · "
          f"channels: {', '.join(c.name for c in channels)}")
    print("  chat commands: /help · /new · /restart (soft) · /hard_restart "
          "— hyphens, /restart-gateway, and @bot suffix all accepted")
    threads = []
    for ch in channels:
        t = threading.Thread(target=ch.start, args=(gateway,), daemon=True)
        t.start()
        threads.append(t)
    try:
        last_sweep = time.monotonic()
        while any(t.is_alive() for t in threads):
            for t in threads:
                t.join(timeout=0.5)
            if time.monotonic() - last_sweep >= 60:   # evict idle warm sessions
                gateway._claude_sessions.sweep()
                last_sweep = time.monotonic()
    except KeyboardInterrupt:
        print("\ngateway stopping…")
    finally:
        gateway.shutdown()
    return 0
