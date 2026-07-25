"""Gateway control plane: session-per-conversation routing over channels."""

from __future__ import annotations

import re
import threading
import time
from typing import Any

from .. import config, models, pools, promptgate, security, store
from ..claude_session import ClaudeStreamSession
from ..runtime import ConfigError, Session, build_session
from .workflow import WORKFLOW_POLICY, is_running as workflow_is_running

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
    ("effort", "List or select Codex reasoning effort (auto-restarts to apply)",
     {"effort", "reasoning"}),
    ("update", "Remote update — pull new code from the repo, then auto restart",
     {"update", "upgrade", "pull"}),
    ("pending", "List pending approvals (approve/reject from chat)",
     {"pending", "approvals", "review"}),
    ("deny", "Refuse a pending action with a reason — /deny <id> <why>",
     {"deny", "refuse"}),
    ("remind", "Schedule a daily message — /remind 09:00 <what to do>; "
     "/remind list; /remind del <id>",
     {"remind", "cron", "schedule"}),
]

# Friendly short model names accepted by `claude --model` (full claude-… IDs also OK).
_GATEWAY_MODELS = ["opus", "sonnet", "haiku"]            # claude-cli suggestions
_CODEX_REASONING_EFFORTS = ["default", "low", "medium", "high", "xhigh"]
# Commands that pull code / restart the service / rewrite config — gated to
# trusted channels only (see Gateway._command_trusted).
_PRIVILEGED_COMMANDS = {"update", "models", "effort", "restart", "hard_restart",
                        "pending", "deny", "remind"}
# Providers with a warm persistent-session implementation (see
# claude_session.ClaudeStreamSession / codex_session.CodexAppServerSession).
_PERSISTENT_PROVIDERS = ("claude-cli", "codex-cli")
TURN_ERROR_REPLY = ("⚠️ 문제가 생겨서 이번 메시지를 처리하지 못했어요. "
                    "잠시 후 다시 시도해 주세요.")
_TELEGRAM_EXECUTION_POLICY = (
    "<gateway-execution-policy>\n"
    + WORKFLOW_POLICY
    + "Keep this foreground turn responsive: inspect only files relevant to the "
    "request and run only targeted tests. Do not wait for a repository-wide "
    "test suite. If broader verification is warranted, start it as a detached "
    "background job, write its output and exit status to a receipt inside the "
    "workspace, and tell the user the receipt path.\n"
    "</gateway-execution-policy>\n\n"
)


def _gateway_model_choices(provider: str, cfg: dict[str, Any]) -> list[str]:
    if provider == "codex-cli":
        return models.codex_model_ids(cfg)
    if provider == "claude-cli":
        return _GATEWAY_MODELS
    if provider in config.KNOWN_MODELS:
        return [model for model, _note in config.KNOWN_MODELS[provider]]
    current = str(cfg.get("model") or "")
    return [current] if current else []


def _model_fits_provider(provider: str, name: str) -> bool:
    """A cross-family model name must never reach the wrong CLI: a stale
    gateway_model='sonnet' left over from a claude-cli era 400s every codex
    turn ('The sonnet model is not supported when using Codex…')."""
    n = (name or "").lower()
    if not n:
        return False
    if provider == "codex-cli":
        return not (n in ("opus", "sonnet", "haiku") or n.startswith("claude"))
    if provider == "claude-cli":
        return not n.startswith(("gpt", "codex", "o3", "o4"))
    return True


def _gateway_model_accepted(provider: str, name: str, known: list[str]) -> bool:
    """claude-cli is validated against the known set; other providers pass the
    model id through (codex/the API validate it themselves) — except a name
    from the WRONG family, which is rejected up front."""
    if not name:
        return False
    if provider == "codex-cli":
        return name in known
    if provider == "claude-cli":
        return name in known or name.startswith("claude-")
    return _model_fits_provider(provider, name)


def _numbered_choice(value: str, choices: list[str]) -> str:
    if not value.isdecimal():
        return value
    index = int(value) - 1
    return choices[index] if 0 <= index < len(choices) else ""


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
    """Welcome + grouped command list. Telegram auto-sends /start on first
    open, so this doubles as the onboarding message: a one-line intro and an
    example come first, then chat commands, then admin commands."""
    chat_cmds = [(c, d) for c, d, _ in _GATEWAY_COMMANDS
                 if c not in _PRIVILEGED_COMMANDS]
    admin_cmds = [(c, d) for c, d, _ in _GATEWAY_COMMANDS
                  if c in _PRIVILEGED_COMMANDS]
    lines = [
        "👋 안녕하세요, birkin이에요 — 당신을 기억하는 AI 에이전트입니다.",
        "그냥 평소처럼 말 걸어 주세요. 예: \"내일 3시 회의 준비 도와줘\"",
        "대화는 기억으로 남고, 밤사이 스스로 정리해 아침에 알려드려요.",
        "",
        "💬 명령:",
    ]
    lines += [f"/{c} — {d}" for c, d in chat_cmds]
    if admin_cmds:
        lines += ["", "🔧 관리자용 (신뢰 채널 전용):"]
        lines += [f"/{c} — {d}" for c, d in admin_cmds]
    return "\n".join(lines)


def command_menu() -> list[dict[str, str]]:
    """Payload for Telegram setMyCommands (canonical, [a-z0-9_] names only)."""
    return [{"command": c, "description": d} for c, d, _ in _GATEWAY_COMMANDS]


# Shared friendly tail so soft + hard restart greet the same way.
_BACK_GREETING = "다시 왔습니다 👋 무엇을 도와드릴까요?"
# Sent by the re-exec'd process after a HARD restart (code + config reloaded).
_RESTART_GREETING = "✅ 재시작 완료! 코드·설정을 새로 반영했어요. " + _BACK_GREETING


def _split_schedule(arg: str) -> tuple[dict[str, Any] | None, str]:
    """Split ``"<schedule> <task>"``, trying the longest schedule prefix first.

    Longest-first matters: "0 9 * * 1 weekly review" must be read as a 5-field
    cron expression, not as the one-token schedule "0". 3 covers the Korean
    weekly form ("매주 월요일 09:00 주간 리뷰") — without it the parser accepts
    the expression but the splitter never hands it three tokens.
    """
    from .. import cron
    tokens = arg.split()
    for n in (5, 3, 2, 1):
        if len(tokens) <= n:      # a reminder needs a task after the schedule
            continue
        spec = cron.parse_schedule(" ".join(tokens[:n]))
        if spec is not None:
            return spec, " ".join(tokens[n:]).strip()
    return None, arg


def _restart_marker_path():
    """One-shot marker dropped before a hard re-exec so the new process can greet
    the chat that asked for the restart."""
    from .. import config
    return config.birkin_home() / "restart_notice.json"


class Gateway:
    def __init__(self, cfg: dict[str, Any]):
        # The gateway may use its own (faster) model without affecting the REPL
        # or the nightly routine: config "gateway_model" overrides "model" for
        # this service only. A stale override from ANOTHER provider family
        # (e.g. 'sonnet' left over after switching to codex-cli) is ignored —
        # applying it would 400 every turn.
        gw_model = cfg.get("gateway_model")
        provider = cfg.get("provider", "")
        known_models = _gateway_model_choices(provider, cfg)
        if gw_model and _gateway_model_accepted(provider, gw_model, known_models):
            cfg = {**cfg, "model": gw_model}
        elif gw_model:
            print(f"[gateway] ignoring unsupported gateway_model={gw_model!r} "
                  f"for provider {provider!r}; using "
                  f"model={cfg.get('model')!r}")
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
        # conversation) — see _new_claude_session / _make_spare. The
        # generation counter invalidates spares still BUILDING when a
        # restart/shutdown changes config: a builder may only publish into
        # the generation it started in.
        self._spare: ClaudeStreamSession | None = None
        self._spare_lock = threading.Lock()
        self._spare_gen = 0
        # Warm sessions currently running a turn, per (channel, chat_id) — a new
        # message on the same chat interrupts them (mid-input interruption).
        self._inflight: dict[tuple[str, str], list[tuple[Any, Any]]] = {}
        self._inflight_lock = threading.Lock()
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
            # cli_access is already forced to "workspace" in __init__ for the
            # gateway, so codex runs cwd-scoped with no network and can never
            # escalate — regardless of the user's danger-full-access config.
            sandbox = ("danger-full-access"
                       if self.cfg.get("cli_access") == "full"
                       else "workspace-write")
            return CodexAppServerSession(
                model=self.cfg.get("model"),
                preamble=self._system_prompt(),
                reasoning_effort=str(
                    self.cfg.get("gateway_reasoning_effort", "") or ""),
                turn_timeout=float(self.cfg.get("cli_timeout", 300)),
                sandbox_mode=sandbox, approval_policy="never")
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
        with self._spare_lock:
            gen = self._spare_gen             # the generation we build FOR
        try:
            s = self._build_claude_session()
            s.start()
        except Exception as exc:              # warm-up must never take the
            print(f"[gateway] prewarm failed: {exc}", flush=True)  # service down
            return
        with self._spare_lock:
            # Publish only into the generation we started in: a restart/
            # shutdown mid-build means this session carries STALE config —
            # the cold-start window is ~10-30 s, so this race is real
            # (reproduced in review; see test_stale_inflight_spare_...).
            if gen == self._spare_gen and self._spare is None:
                self._spare = s
                return
        s.close()   # stale generation or raced another warm-up — discard

    def prewarm(self) -> None:
        """Public entry: warm the first spare in the background at boot."""
        threading.Thread(target=self._make_spare, daemon=True).start()

    def shutdown(self) -> None:
        self._claude_sessions.clear()   # the pool closes every session
        with self._spare_lock:
            self._spare_gen += 1        # in-flight builders must not publish
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
        # discard it AND bump the generation so a spare still BUILDING for
        # the old config cannot publish itself after this point.
        with self._spare_lock:
            self._spare_gen += 1
            spare, self._spare = self._spare, None
        if spare is not None:
            spare.close()
        cfg = config.load_config()
        if (cfg.get("gateway_model")
                and _model_fits_provider(cfg.get("provider", ""),
                                         cfg["gateway_model"])):
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

    def interrupt(self, channel: str, chat_id: str) -> bool:
        """Cancel the turn currently in flight for this chat, if any. Called by
        a channel when a NEW message arrives mid-turn. Returns True if a turn
        was signalled. Safe to call from a different thread than handle()."""
        with self._inflight_lock:
            owners = tuple(self._inflight.get((channel, str(chat_id)), ()))
        interrupted = False
        seen_sessions: set[int] = set()
        for _token, sess in reversed(owners):
            session_id = id(sess)
            if session_id in seen_sessions:
                continue
            seen_sessions.add(session_id)
            fn = getattr(sess, "interrupt", None)
            if not callable(fn):
                continue
            try:
                interrupted = bool(fn()) or interrupted
            except Exception:
                continue
        return interrupted

    def handle(self, channel: str, chat_id: str, text: str,
               on_text=None, workflow_id: str | None = None) -> str:
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
        skill_query = display_text
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
            skill_query = f"neurosis {display_text}"
            cmd = None                                       # fall through to a turn
        with self._lock:
            # Privileged commands pull code / restart the service / rewrite config.
            # An OPEN Telegram bot (no allowed_chat_ids) must not let strangers
            # trigger them. (When allowed_chat_ids IS set, telegram.py already
            # dropped unauthorized chats before this point.)
            if cmd in _PRIVILEGED_COMMANDS and not self._command_trusted(channel):
                return ("This command is restricted. Set "
                        "channels.telegram.allowed_chat_ids so only you can run "
                        "/update, /models, /effort, /restart and /hard_restart.")
            if cmd == "help":
                return gateway_help_text()
            if cmd == "models":
                reply = self._models_command(cmd_arg)
                if self._hard_restart:   # /models scheduled a re-exec
                    self._restart_origin = (channel, str(chat_id))
                return reply
            if cmd == "effort":
                reply = self._effort_command(cmd_arg)
                if self._hard_restart:
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
            if cmd == "pending":
                return self.pending_text()
            if cmd == "deny":
                return self.deny_command(cmd_arg)
            if cmd == "remind":
                return self.remind_command(cmd_arg, channel, str(chat_id))
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
            inflight_token = object()
            if persistent:
                try:
                    sess = self._claude_sessions.borrow(key)
                except pools.SessionPoolFullError:
                    return TURN_ERROR_REPLY
            else:
                sess = None

        try:
            t0 = time.monotonic()
            if persistent:
                try:
                    # Track the in-flight session so a new message on the same
                    # chat can interrupt() this turn (mid-input interruption).
                    with self._inflight_lock:
                        self._inflight.setdefault(key, []).append(
                            (inflight_token, sess))
                except RuntimeError as exc:
                    dt = time.monotonic() - t0
                    print(f"[gateway] {channel}:{chat_id} ✗ error after "
                          f"{dt:.1f}s: {exc}", flush=True)
                    return TURN_ERROR_REPLY

            trusted_telegram = (channel == "telegram"
                                and self._command_trusted(channel))
            approved_work = bool(
                trusted_telegram
                and workflow_id
                and workflow_is_running(workflow_id, str(chat_id))
            )
            if trusted_telegram:
                text = _TELEGRAM_EXECUTION_POLICY + text
            print(f"[gateway] {channel}:{chat_id} « {display_text[:80]}", flush=True)
            try:
                if persistent:
                    # Warm Claude Code process keeps its own conversation context,
                    # so only the new turn is sent.
                    skill_state = getattr(sess, "_birkin_skill_state", None)
                    if skill_state is None:
                        skill_state = {"revision": -1, "names": set()}
                        setattr(sess, "_birkin_skill_state", skill_state)
                    reply = sess.ask(
                        self.session._prepare_cli_turn(
                            text, route_query=skill_query,
                            skill_state=skill_state),
                        on_text=on_text)
                else:
                    # The non-persistent path shares the single self.session, so its
                    # history swap must stay serialized under the global lock.
                    with self._lock:
                        self.session.agent.messages = self._chats.get(key, [])
                        ctx = getattr(self.session, "ctx", None)
                        old_required = getattr(
                            ctx, "subagent_approval_required", False)
                        old_approved = getattr(ctx, "approved_work", False)
                        if ctx is not None:
                            ctx.subagent_approval_required = trusted_telegram
                            ctx.approved_work = approved_work
                        try:
                            reply = self.session.ask(
                                text,
                                review_skills=self._command_trusted(channel),
                                route_query=skill_query)
                        finally:
                            if ctx is not None:
                                ctx.subagent_approval_required = old_required
                                ctx.approved_work = old_approved
                            self._chats[key] = self.session.agent.messages
            except Exception as exc:
                dt = time.monotonic() - t0
                # Full detail to the server log; a friendly line to the chat —
                # the raw exception can leak paths/internals to a Telegram user.
                print(f"[gateway] {channel}:{chat_id} ✗ error after "
                      f"{dt:.1f}s: {exc}", flush=True)
                return TURN_ERROR_REPLY
            dt = time.monotonic() - t0
            print(f"[gateway] {channel}:{chat_id} » {len(reply or '')} chars in "
                  f"{dt:.1f}s", flush=True)
            store.append_activity(
                f"gateway[{channel}:{chat_id}]: {display_text[:100]}")
            if persistent:
                self.session._record_turn(
                    display_text, reply or "",
                    review_skills=self._command_trusted(channel))
            # Auto-save the turn so the nightly Morpheus routine can extract
            # memory — but ONLY for trusted conversations (an open Telegram bot's
            # strangers must not be persisted into long-term memory). Runs OUTSIDE
            # the global lock; transcripts.append_turn is per-conversation locked.
            if self._autosave_trusted(channel):
                from .. import transcripts
                transcripts.append_turn(
                    channel, str(chat_id), display_text, reply or "", cfg=self.cfg)
            return reply or "(no reply)"
        finally:
            if persistent:
                try:
                    with self._inflight_lock:
                        owners = self._inflight.get(key)
                        if owners is not None:
                            for index, owner in enumerate(owners):
                                if owner[0] is inflight_token:
                                    owners.pop(index)
                                    break
                        if not owners:
                            self._inflight.pop(key, None)
                finally:
                    self._claude_sessions.release(key, sess)

    def _models_command(self, arg: str) -> str:
        """List the gateway model, or select one and schedule a hard restart so the
        new model takes effect (the gateway's model is fixed at process start).
        Called under the lock."""
        parts = (arg or "").strip().split()
        provider = self.cfg.get("provider", "")
        known = _gateway_model_choices(provider, self.cfg)
        listing = "\n".join(f"{i}. {model}" for i, model in enumerate(known, 1))
        if not parts:
            kind = "CLI" if provider.endswith("-cli") else "API"
            auth = "계정 로그인" if kind == "CLI" else "API key"
            lines = [f"현재 게이트웨이 모델: {self.cfg.get('model')} [{provider}]",
                     f"연결 방식: {kind} ({auth})",
                     f"사용 가능 - {kind} 모델 ({provider}):", listing,
                     "모델 선택: /models <번호>  예: /models 1"]
            return "\n".join(lines)
        name = _numbered_choice(parts[0], known)
        if not _gateway_model_accepted(provider, name, known):
            return (f"'{parts[0]}'은(는) 모르는 모델이에요. "
                    "사용 가능한 번호는 /models에서 확인하세요.")
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

    def _effort_command(self, arg: str) -> str:
        if self.cfg.get("provider") != "codex-cli":
            return "Effort 설정은 codex-cli에서만 사용할 수 있어요."
        value = (arg or "").strip().split()[0] if (arg or "").strip() else ""
        listing = "\n".join(
            f"{i}. {level}"
            for i, level in enumerate(_CODEX_REASONING_EFFORTS, 1))
        if not value:
            current = self.cfg.get("gateway_reasoning_effort") or "default"
            return (f"현재 effort: {current}\n{listing}\n"
                    "변경: /effort <번호>  예: /effort 2")
        effort = _numbered_choice(value, _CODEX_REASONING_EFFORTS)
        if effort not in _CODEX_REASONING_EFFORTS:
            return "모르는 effort예요. /effort에서 번호를 확인하세요."
        stored_effort = "" if effort == "default" else effort
        cfg = config.load_config()
        cfg["gateway_reasoning_effort"] = stored_effort
        config.save_config(cfg)
        self.cfg = {**self.cfg, "gateway_reasoning_effort": stored_effort}
        self._hard_restart = True
        print(f"[gateway] effort → {effort}; scheduling hard restart", flush=True)
        return (f"✅ Gateway effort를 '{effort}'로 바꿨어요. "
                "적용하려고 지금 재시작합니다 — 잠시 후 다시 말 걸어주세요.")

    # -- remote approvals (P0-2: the propose->approve loop, from chat) -------

    def pending_actions(self) -> list[dict[str, Any]]:
        """Pending proposals, highest-risk first (same order as the CLI)."""
        from .. import risk
        return risk.sort_by_risk(store.list_pending())

    def pending_text(self) -> str:
        """Plain-text pending list — the fallback for channels without
        buttons (HTTP) and the body the Telegram channel decorates."""
        from .. import approvals, risk
        items = risk.sort_by_risk(approvals.reviewable_pending())
        if not items:
            return "📭 No pending approvals."
        lines = [f"📋 {len(items)} pending approval(s):"]
        for rec in items[:10]:
            lines.append(f"- [{rec.get('category')}] {rec.get('title')} "
                         f"(id {rec.get('id')})")
        lines.append("Approve/reject in the CLI with `birkin review` — or "
                     "tap the buttons if your channel shows them.")
        return "\n".join(lines)

    def remind_command(self, arg: str, channel: str, chat_id: str) -> str:
        """Schedule a daily prompt reminder delivered to THIS chat (P2-3).

        ``/remind 09:00 <what to do>`` · ``/remind list`` · ``/remind del <id>``.
        Only prompt-type jobs delivered to the current (already-trusted) chat
        are created — never shell, never another chat — so this cannot launder
        code execution or exfiltrate to a stranger. Callers gate on a trusted
        channel first (remind is in _PRIVILEGED_COMMANDS)."""
        from .. import cron
        arg = (arg or "").strip()
        if not arg or arg.lower() in ("list", "ls"):
            jobs = [j for j in cron.load_jobs()
                    if str(j.get("deliver_chat_id")) == chat_id]
            if not jobs:
                return ("등록된 리마인더가 없어요. 예: /remind 09:00 "
                        "오늘 할 일 정리해줘")
            lines = ["⏰ 리마인더:"]
            for j in jobs:
                lines.append(f"- {cron.schedule_display(j)} "
                             f"{j.get('value', '')[:60]} (id {j['id']})")
            lines.append("삭제: /remind del <id>")
            return "\n".join(lines)
        parts = arg.split(maxsplit=1)
        if parts[0].lower() in ("del", "delete", "rm") and len(parts) > 1:
            aid = parts[1].strip()
            job = next((j for j in cron.load_jobs() if j.get("id") == aid), None)
            if not job or str(job.get("deliver_chat_id")) != chat_id:
                return "그 id의 리마인더를 찾지 못했어요 (본인 것만 삭제 가능)."
            try:
                cron.remove_job(aid)
            except store.FileLockTimeout:
                return ("⚠ 리마인더 저장소가 사용 중입니다. "
                        "잠시 후 다시 시도해 주세요.")
            return f"🗑️ 리마인더 삭제됨 (id {aid})."
        # Richer schedules first ("every 30m ...", "2h ...", "0 9 * * 1 ..."),
        # then the original HH:MM / HH시MM form.
        spec, prompt = _split_schedule(arg)
        if spec is None:
            m = re.match(r"(\d{1,2})[:시](\d{2})?\s+(.+)", arg, re.S)
            if not m:
                return ("형식: /remind <시각|주기> <할 일>. 예: /remind 09:00 "
                        "오늘 할 일 정리 · /remind 30분마다 메일 확인 · "
                        "/remind 1시간 후 스트레칭 · /remind 매주 월요일 09:00 "
                        "주간 리뷰 (every 30m · 2h · 0 9 * * 1 도 됩니다)")
            hour = int(m.group(1))
            minute = int(m.group(2) or 0)
            if hour > 23 or minute > 59:
                # reject rather than silently clamp — 25:99 shouldn't become 23:59
                return f"시간이 올바르지 않아요 ({hour:02d}:{minute:02d}). 00:00–23:59 범위로 다시 보내 주세요."
            spec, prompt = {"kind": "daily", "hour": hour, "minute": minute,
                            "display": f"{hour:02d}:{minute:02d} daily"}, \
                m.group(3).strip()
        if not prompt:
            return "할 일을 함께 적어 주세요. 예: /remind 30분마다 메일 확인"
        try:
            job = cron.add_job(name="remind", action_type="prompt",
                               value=prompt, deliver_chat_id=chat_id,
                               schedule=spec)
        except store.FileLockTimeout:
            return ("⚠ 리마인더 저장소가 사용 중입니다. "
                    "잠시 후 다시 시도해 주세요.")
        except ValueError as exc:
            return f"스케줄을 이해하지 못했어요: {exc}"
        return (f"⏰ {cron.schedule_display(job)}에 알려드릴게요: "
                f"\"{prompt[:60]}\" (id {job['id']}, 취소는 /remind del {job['id']})")

    def resolve_action(self, aid: str, approve: bool) -> str:
        """Approve/reject one pending action (the button-tap handler).
        Callers must gate on a trusted channel first."""
        from .. import approvals
        if approve:
            out = approvals.approve(aid)
            if not out.get("ok"):
                return f"⚠ {out.get('error', 'approve failed')}"
            store.append_activity(f"approval[{aid}]: approved via gateway")
            return f"✅ approved — {out.get('result', '')}"[:500]
        out = approvals.reject(aid)
        if not out.get("ok"):
            return "⚠ not found or already resolved"
        store.append_activity(f"approval[{aid}]: rejected via gateway")
        return "❌ rejected"

    def deny_command(self, arg: str) -> str:
        """/deny <id> <reason> — refuse, and tell the agent why."""
        from .. import approvals
        parts = (arg or "").strip().split(None, 1)
        if not parts:
            return "형식: /deny <id> <이유>  (대기 목록은 /pending)"
        aid, reason = parts[0], (parts[1] if len(parts) > 1 else "")
        out = approvals.reject(aid, reason=reason)
        if not out.get("ok"):
            return "⚠ not found or already resolved"
        store.append_activity(
            f"approval[{aid}]: rejected via gateway"
            + (f" — {reason[:120]}" if reason else ""))
        return ("❌ 거부했습니다." if not reason
                else f"❌ 거부했습니다 — 사유를 에이전트에게 전달합니다: {reason[:200]}")

    def claim_action(self, aid: str) -> tuple[str, bool]:
        from .. import approvals
        out = approvals.claim(aid)
        if not out.get("ok"):
            return f"⚠ {out.get('error', 'approve failed')}", False
        return "✅ approved — 실행 중", True

    def execute_claimed_action(self, aid: str) -> str:
        from .. import approvals
        out = approvals.execute_claimed(aid)
        if not out.get("ok"):
            return f"⚠ {out.get('error', 'approve failed')}"
        store.append_activity(f"approval[{aid}]: approved via gateway")
        return f"✅ approved — {out.get('result', '')}"[:500]

    def restore_action_claim(self, aid: str) -> None:
        from .. import approvals
        approvals.restore_claim(aid)

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
