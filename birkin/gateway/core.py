"""Gateway control plane: session-per-conversation routing over channels."""

from __future__ import annotations

import re
import sys
import threading
import time
from collections.abc import Callable, Hashable
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import (
    Final,
    Protocol,
    TypeGuard,
    TypeVar,
    TypedDict,
    runtime_checkable,
)

from typing_extensions import NotRequired, override

from .. import config, models, pools, promptgate, security, store
from ..approval_execution_codec import JSONValue
from ..claude_session import ClaudeStreamSession
from ..codex_session import CodexAppServerSession
from ..omo import OmoController
from ..runtime import ConfigError, Session, build_session
from .telegram_lease import (
    TelegramGatewayLease,
    TelegramGatewayLeaseRaceError,
    TelegramGatewayOwnedError,
)
from .turn_types import AskSession, ProgressCallback, TextCallback
from .turn_support import (
    GATEWAY_COMMANDS as _GATEWAY_COMMANDS,
    LOCAL_TRUSTED_CHANNELS as _LOCAL_TRUSTED_CHANNELS,
    PERSISTENT_PROVIDERS as _PERSISTENT_PROVIDERS,
    TURN_ERROR_REPLY as TURN_ERROR_REPLY,
    TURN_INTERRUPTED_REPLY as TURN_INTERRUPTED_REPLY,
    TURN_MOIRAI_RECOVERY_ERROR_REPLY as TURN_MOIRAI_RECOVERY_ERROR_REPLY,
    TURN_PARTIAL_SUFFIX as TURN_PARTIAL_SUFFIX,
    UNTRUSTED_CHANNEL_REPLY as UNTRUSTED_CHANNEL_REPLY,
    ask_session as ask_session,
    conversation_session_id as conversation_session_id,
    gateway_help_text as gateway_help_text,
    match_command as match_command,
    TurnContract,
)

_T = TypeVar("_T")
GatewayConfig = dict[str, JSONValue]
WarmSession = ClaudeStreamSession | CodexAppServerSession
InflightOwner = tuple[object, AskSession, threading.Event]


class _TextStream(Protocol):
    @override
    def __getattribute__(self, name: str, /) -> object: ...

    def write(self, data: str) -> int: ...

    def flush(self) -> None: ...

    def isatty(self) -> bool: ...


@runtime_checkable
class _StoreInternals(Protocol):
    def _write_json(self, path: Path, data: dict[str, JSONValue]) -> None: ...

    def _read_json(self, path: Path, default: None) -> JSONValue: ...

    def write_json(self, path: Path, data: dict[str, JSONValue]) -> None:
        self._write_json(path, data)

    def read_json(self, path: Path) -> JSONValue:
        return self._read_json(path, None)


def _has_store_internals(module: ModuleType) -> TypeGuard[_StoreInternals]:
    return hasattr(module, "_write_json") and hasattr(module, "_read_json")


def _int_setting(value: JSONValue, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, (str, int, float)):
        return int(value or default)
    raise TypeError("setting cannot be converted to int")


def _float_setting(value: JSONValue, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, (str, int, float)):
        return float(value or default)
    raise TypeError("setting cannot be converted to float")


def _is_conversation_key(value: Hashable) -> TypeGuard[tuple[str, str]]:
    match value:
        case (str(), str()):
            return True
        case _:
            return False


@runtime_checkable
class _InterruptibleSession(Protocol):
    def interrupt(self) -> bool: ...


class _QuietHours(TypedDict, total=False):
    start: str
    end: str


class _CompanionPolicy(TypedDict, total=False):
    enabled: bool
    timezone: str
    quiet_hours: _QuietHours
    daily_cap: int


class _Commitment(TypedDict):
    status: str
    outcome: str
    next_action: NotRequired[str]
    check_in_at: NotRequired[str]
    source_ref: NotRequired[str]


class _RiskModule(Protocol):
    def sort_by_risk(self, records: list[dict[str, _T]]) -> list[dict[str, _T]]: ...


def _has_risk_contract(module: ModuleType) -> TypeGuard[_RiskModule]:
    return hasattr(module, "sort_by_risk")


class _DeliveryRegistryModule(Protocol):
    def resolve_delivery_target(
        self,
        name: str,
        cfg: GatewayConfig,
        *,
        fallback: Callable[[str], object] | None = None,
    ) -> object | None: ...


def _has_delivery_registry_contract(
    module: ModuleType,
) -> TypeGuard[_DeliveryRegistryModule]:
    return hasattr(module, "resolve_delivery_target")


class _CompanionModule(Protocol):
    def pause_all(self) -> dict[str, JSONValue]: ...

    def resume(self) -> dict[str, JSONValue]: ...

    def get_policy(self) -> _CompanionPolicy: ...

    def list_commitments(self, *, context_id: str = "") -> list[_Commitment]: ...


def _has_companion_contract(module: ModuleType) -> TypeGuard[_CompanionModule]:
    return all(
        hasattr(module, name)
        for name in ("pause_all", "resume", "get_policy", "list_commitments")
    )


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TimestampedStream:
    """Stamp every completed line written to a gateway stream.

    gateway.log carried no clock at all, so `✗ error after 3543.6s` could not
    be lined up with the journal row for the same death. Stamping is done here
    rather than at each print() so the codex heartbeats — written by another
    module entirely — are covered too. Partial writes stay buffered until
    their newline arrives, or a streamed line would be cut into stamped
    fragments.
    """

    def __init__(self, stream: _TextStream) -> None:
        self._stream: _TextStream = stream
        self._buffer: str = ""
        self._lock: threading.Lock = threading.Lock()

    def write(self, data: str) -> int:
        with self._lock:
            self._buffer += data
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                _ = self._stream.write(f"[{_utc_stamp()}] {line}\n")
        return len(data)

    def flush(self) -> None:
        with self._lock:
            self._stream.flush()

    def isatty(self) -> bool:
        try:
            return bool(self._stream.isatty())
        except (AttributeError, OSError):
            return False

    def __getattr__(self, name: str) -> object:
        # getattr(), not __getattribute__(): the wrapped stream may expose
        # .encoding/.buffer/.fileno through its own __getattr__ (colorama's
        # AnsiToWin32, pytest's capture), which __getattribute__ skips.
        return getattr(self._stream, name)


class _SystemStreams(Protocol):
    stdout: _TextStream | TimestampedStream
    stderr: _TextStream | TimestampedStream


def _has_system_streams(module: ModuleType) -> TypeGuard[_SystemStreams]:
    return hasattr(module, "stdout") and hasattr(module, "stderr")


def install_timestamped_logging() -> None:
    system_module: ModuleType = sys
    if not _has_system_streams(system_module):
        raise RuntimeError("system text streams are unavailable")
    if not isinstance(system_module.stdout, TimestampedStream):
        system_module.stdout = TimestampedStream(system_module.stdout)
    if not isinstance(system_module.stderr, TimestampedStream):
        system_module.stderr = TimestampedStream(system_module.stderr)


def _configured_workspace(cfg: GatewayConfig) -> str | None:
    roots = cfg.get("workspace_roots")
    if not isinstance(roots, list):
        return None
    for root in roots:
        path = Path(str(root)).expanduser()
        if path.is_dir():
            return str(path)
    return None


# Gateway chat commands. Each: (canonical name, description, {accepted triggers}).
# Triggers include hyphen / underscore / run-together variants because Telegram
# bot commands only allow [a-z0-9_] (no hyphen), while users still type hyphens.

# Friendly short model names accepted by `claude --model` (full claude-… IDs also OK).
_GATEWAY_MODELS = ["opus", "sonnet", "haiku"]  # claude-cli suggestions
_CODEX_REASONING_EFFORTS = ["default", "low", "medium", "high", "xhigh"]
# Commands that pull code / restart the service / rewrite config — gated to
# trusted channels only (see Gateway._command_trusted).
# Providers with a warm persistent-session implementation (see
# claude_session.ClaudeStreamSession / codex_session.CodexAppServerSession).


def _gateway_model_choices(provider: str, cfg: GatewayConfig) -> list[str]:
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


def command_menu() -> list[dict[str, str]]:
    """Payload for Telegram setMyCommands (canonical, [a-z0-9_] names only)."""
    return [{"command": c, "description": d} for c, d, _ in _GATEWAY_COMMANDS]


# Shared friendly tail so soft + hard restart greet the same way.
_BACK_GREETING: Final = "다시 왔습니다 👋 무엇을 도와드릴까요?"
# Sent by the re-exec'd process after a HARD restart (code + config reloaded).
_RESTART_GREETING: Final = (
    "✅ 재시작 완료! 코드·설정을 새로 반영했어요. " + _BACK_GREETING
)


def _split_schedule(arg: str) -> tuple[dict[str, JSONValue] | None, str]:
    """Split ``"<schedule> <task>"``, trying the longest schedule prefix first.

    Longest-first matters: "0 9 * * 1 weekly review" must be read as a 5-field
    cron expression, not as the one-token schedule "0". 3 covers the Korean
    weekly form ("매주 월요일 09:00 주간 리뷰") — without it the parser accepts
    the expression but the splitter never hands it three tokens.
    """
    from .. import cron

    tokens = arg.split()
    for n in (5, 3, 2, 1):
        if len(tokens) <= n:  # a reminder needs a task after the schedule
            continue
        spec = cron.parse_schedule(" ".join(tokens[:n]))
        if spec is not None:
            return spec, " ".join(tokens[n:]).strip()
    return None, arg


def _restart_marker_path() -> Path:
    """One-shot marker dropped before a hard re-exec so the new process can greet
    the chat that asked for the restart."""
    from .. import config

    return config.birkin_home() / "restart_notice.json"


class Gateway:
    cfg: GatewayConfig
    session: Session
    _lock: threading.Lock
    _persistent: bool
    _claude_sessions: pools.SessionPool
    _spare: WarmSession | None
    _spare_lock: threading.Lock
    _spare_gen: int
    _inflight: dict[tuple[str, str], list[InflightOwner]]
    _inflight_lock: threading.Lock
    _hard_restart_lock: threading.Lock
    _hard_restart: bool
    _restart_origin: tuple[str, str] | None
    _restart_notice: dict[str, JSONValue] | None
    _omo_controller: OmoController
    _telegram_lease: TelegramGatewayLease | None

    def __init__(self, cfg: GatewayConfig) -> None:
        # A reachable conversation must never inherit the operator's legacy
        # global goal. Gateway turns use only their deterministic session goal.
        cfg = {**cfg, "session_goal_fallback": False}
        # The gateway may use its own (faster) model without affecting the REPL
        # or the nightly routine: config "gateway_model" overrides "model" for
        # this service only. A stale override from ANOTHER provider family
        # (e.g. 'sonnet' left over after switching to codex-cli) is ignored —
        # applying it would 400 every turn.
        gw_model_value = cfg.get("gateway_model")
        gw_model = gw_model_value if isinstance(gw_model_value, str) else ""
        provider_value = cfg.get("provider", "")
        provider = provider_value if isinstance(provider_value, str) else ""
        known_models = _gateway_model_choices(provider, cfg)
        if gw_model and _gateway_model_accepted(provider, gw_model, known_models):
            cfg = {**cfg, "model": gw_model}
        elif gw_model:
            print(
                f"[gateway] ignoring unsupported gateway_model={gw_model!r} "
                + f"for provider {provider!r}; using "
                + f"model={cfg.get('model')!r}"
            )
        # SECURITY: the gateway is reachable over channels, so a chat message must
        # never reach a Claude process running with --dangerously-skip-permissions.
        # Force the safe access level here regardless of the global config.
        if cfg.get("cli_access") == "full":
            print(
                "[gateway] cli_access 'full' is unsafe for a reachable service "
                + "— using 'workspace' for the gateway.",
                flush=True,
            )
            cfg = {**cfg, "cli_access": "workspace"}
        self.cfg = cfg
        self.session = build_session(cfg)  # may raise ConfigError
        self._chats: dict[tuple[str, str], list[dict[str, object]]] = {}
        self._last_substantive_requests: dict[tuple[str, str], str] = {}
        # Conversation keys whose first turn already carried the transcript
        # tail (or explicitly declined it via /new). Guarded by self._lock.
        # Without this seed, a gateway restart forgets every conversation:
        # transcripts.append_turn writes history to disk but nothing ever
        # read it back.
        self._history_seeded: set[tuple[str, str]] = set()
        self._lock = threading.Lock()

        # Persistent (warm) CLI processes — one per conversation — for the
        # claude-cli (stream-json) and codex-cli (app-server) providers.
        # Pays cold-start once; warm replies are ~model-time.
        self._persistent = (
            bool(cfg.get("gateway_persistent", True))
            and cfg.get("provider") in _PERSISTENT_PROVIDERS
        )
        # Pool with idle-TTL + LRU cap: dead chats stop holding a live claude
        # process (daemon resource layer; docs/hermes-comparison.md §4).
        self._claude_sessions = pools.SessionPool(
            self._new_claude_session,
            max_sessions=_int_setting(cfg.get("gateway_max_sessions"), 8),
            idle_ttl=_float_setting(cfg.get("gateway_session_ttl_s"), 3600),
        )
        # Pre-warmed spare session (fungible; adopted by the next new
        # conversation) — see _new_claude_session / _make_spare. The
        # generation counter invalidates spares still BUILDING when a
        # restart/shutdown changes config: a builder may only publish into
        # the generation it started in.
        self._spare = None
        self._spare_lock = threading.Lock()
        self._spare_gen = 0
        # Warm sessions currently running a turn, per (channel, chat_id) — a new
        # message on the same chat interrupts them (mid-input interruption).
        self._inflight = {}
        self._inflight_lock = threading.Lock()
        self._hard_restart_lock = threading.Lock()
        # Set by a /hard-restart command; the channel re-execs after replying.
        self._hard_restart = False
        # (channel, chat_id) that triggered a hard restart — persisted across the
        # re-exec so the new process can greet that chat that it is back up.
        self._restart_origin = None
        # Loaded by run() from the restart marker after a re-exec (one-shot).
        self._restart_notice = None
        self._omo_controller = OmoController()
        try:
            self._telegram_lease = TelegramGatewayLease.acquire_for_config(self.cfg)
        except (OSError, RuntimeError):
            self._omo_controller.close()
            raise

    def _system_prompt(self, *, trusted: bool = True) -> str:
        """birkin persona + memory + skill index, snapshot for a warm session.
        Composed through the Prompt-Gate (promptgate) like every other surface."""
        if not trusted:
            return promptgate.compose_public()
        try:
            idx = self.session.skills.index()
        except Exception:
            idx = ""
        extra = (
            (
                "\n\n## birkin skills available\n"
                + "Read the referenced SKILL.md with your own file tools to "
                + "follow one when it fits the task.\n"
                + idx
            )
            if idx
            else ""
        )
        return promptgate.compose_cli(
            self.cfg,
            memory_block=self.session.memory.render() if trusted else "",
            extra=extra,
            include_turn_state=False,
            persona_text=None if trusted else "",
        )

    def _new_claude_session(
        self,
        key: Hashable,
    ) -> ClaudeStreamSession | CodexAppServerSession:
        """SessionPool factory: one warm session per conversation key.

        A pre-warmed spare (see :meth:`prewarm`) is adopted first: gateway
        sessions are configured identically, so the spare is fungible and the
        first message of a new conversation skips the ~28 s cold start.
        """
        if not _is_conversation_key(key):
            raise TypeError("gateway session key must be a channel/chat tuple")
        channel, _chat_id = key
        trusted = self._command_trusted(channel)
        if trusted:
            with self._spare_lock:
                spare, self._spare = self._spare, None
            if spare is not None and spare.is_alive():
                # Replace the trusted spare for the next trusted conversation.
                threading.Thread(target=self._make_spare, daemon=True).start()
                return spare
        return self._build_claude_session(trusted=trusted)

    def _build_claude_session(
        self,
        *,
        trusted: bool = True,
    ) -> ClaudeStreamSession | CodexAppServerSession:
        """Warm session for the configured provider (claude or codex)."""
        model_value = self.cfg.get("model")
        model = model_value if isinstance(model_value, str) else None
        system_prompt = (
            self._system_prompt() if trusted else self._system_prompt(trusted=False)
        )
        if self.cfg.get("provider") == "codex-cli":
            # cli_access is already forced to "workspace" in __init__ for the
            # gateway, so codex stays cwd-scoped and can never escalate —
            # network is granted independently of host filesystem access.
            sandbox = (
                "danger-full-access"
                if self.cfg.get("cli_access") == "full"
                else "workspace-write"
            )
            return CodexAppServerSession(
                model=model,
                cwd=_configured_workspace(self.cfg),
                preamble=system_prompt,
                reasoning_effort=str(
                    self.cfg.get("gateway_reasoning_effort", "") or ""
                ),
                turn_timeout=_float_setting(self.cfg.get("cli_timeout"), 300),
                sandbox_mode=sandbox,
                approval_policy="never",
                network_access=(
                    sandbox == "workspace-write"
                    and self.cfg.get("cli_network_access", False) is True
                ),
                # Without this the gateway has NO birkin tools at all: on a
                # CLI provider birkin's own registry is unreachable (the child
                # runs its own tool loop), and nothing attached the MCP server
                # here. So "remember that I'm called Jane" came back as "I
                # have no local memory path" — birkin's headline feature, and
                # the gateway could not do it. memory/skills/propose_action
                # only; propose_action still queues to `birkin review`.
                birkin_mcp=trusted,
                birkin_mcp_scope="full",
            )
        # Tools the headless gateway may use without a permission prompt
        # (e.g. company MCP servers). Empty -> rely on Claude Code settings.
        allowed_value = self.cfg.get("gateway_allowed_tools", [])
        allowed = (
            [str(tool) for tool in allowed_value if tool]
            if isinstance(allowed_value, list)
            else []
        )
        extra = ["--allowedTools", ",".join(allowed)] if allowed else None
        # Headless children run with the user's interactive hook stack
        # DISABLED and a bounded thinking budget — measured at 3-6 s/turn of
        # hooks + 2.8 s TTFT of default thinking (hermes-comparison.md §6).
        settings = (
            {"disableAllHooks": True}
            if self.cfg.get("gateway_clean_hooks", True)
            else None
        )
        env_extra = {
            "MAX_THINKING_TOKENS": str(
                _int_setting(self.cfg.get("gateway_thinking_tokens"), 0)
            )
        }
        egress_cfg = self.cfg.get("egress", {})
        egress_enforced = (
            isinstance(egress_cfg, dict)
            and bool(egress_cfg)
            and bool(egress_cfg.get("enabled", True))
            and bool(egress_cfg.get("enforced", True))
        )
        cli_access_value = self.cfg.get("cli_access", "workspace")
        cli_access = (
            cli_access_value if isinstance(cli_access_value, str) else "workspace"
        )
        return ClaudeStreamSession(
            model=model,
            cli_access=cli_access,
            append_system_prompt=system_prompt,
            extra_args=extra,
            settings=settings,
            env_extra=env_extra,
            birkin_mcp=trusted,
            egress_enforced=egress_enforced,
            tool_free=not trusted,
        )

    def _make_spare(self) -> None:
        """Spawn one warm, unclaimed session so the next new conversation
        skips the CLI cold start. Never raises (best-effort warm-up)."""
        if not self._persistent or not self.cfg.get("gateway_prewarm", True):
            return
        with self._spare_lock:
            gen = self._spare_gen  # the generation we build FOR
        try:
            s = self._build_claude_session()
            s.start()
        except Exception as exc:  # warm-up must never take the
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
        s.close()  # stale generation or raced another warm-up — discard

    def prewarm(self) -> None:
        """Public entry: warm the first spare in the background at boot."""
        threading.Thread(target=self._make_spare, daemon=True).start()

    def shutdown(self) -> None:
        try:
            self._omo_controller.close()
            self._claude_sessions.clear()  # the pool closes every session
            with self._spare_lock:
                self._spare_gen += 1  # in-flight builders must not publish
                spare, self._spare = self._spare, None
            if spare is not None:
                spare.close()
        finally:
            if self._telegram_lease is not None:
                self._telegram_lease.release()

    def restart(self) -> str:
        """Soft-restart the gateway in place (channels stay up).

        Reloads config + persona + memory + skills + MCP allow-list and tears
        down every warm Claude session, so the next message reflects current
        settings. Conversations start fresh. The process is NOT killed, so code
        changes still require restarting `birkin gateway`. Callers hold the lock.
        """
        assert self._lock.locked(), "restart() must be called holding self._lock"
        self._claude_sessions.clear()  # the pool closes every session
        self._chats.clear()
        # The pre-warmed spare carries a PRE-restart persona/config snapshot —
        # discard it AND bump the generation so a spare still BUILDING for
        # the old config cannot publish itself after this point.
        with self._spare_lock:
            self._spare_gen += 1
            spare, self._spare = self._spare, None
        if spare is not None:
            spare.close()
        cfg: GatewayConfig = config.load_config()
        provider_value = cfg.get("provider", "")
        provider = provider_value if isinstance(provider_value, str) else ""
        gateway_model_value = cfg.get("gateway_model")
        gateway_model = (
            gateway_model_value if isinstance(gateway_model_value, str) else ""
        )
        known_models = _gateway_model_choices(provider, cfg)
        if gateway_model and _gateway_model_accepted(
            provider,
            gateway_model,
            known_models,
        ):
            cfg = {**cfg, "model": cfg["gateway_model"]}
        if cfg.get("cli_access") == "full":
            cfg = {**cfg, "cli_access": "workspace"}
        cfg = {**cfg, "session_goal_fallback": False}
        self.cfg = cfg
        self._persistent = (
            bool(cfg.get("gateway_persistent", True))
            and cfg.get("provider") in _PERSISTENT_PROVIDERS
        )
        try:
            self.session = build_session(cfg)
        except ConfigError as exc:
            return f"[restart] config error: {exc}"
        self.prewarm()  # rebuild the spare from the RELOADED config
        return (
            "♻️ Gateway restarted — reloaded config, persona, memory and "
            + "skills; warm sessions cleared (conversations start fresh).\n\n"
            + _BACK_GREETING
        )

    def load_restart_notice(self, notice: dict[str, JSONValue]) -> None:
        self._restart_notice = notice

    @property
    def persistent(self) -> bool:
        return self._persistent

    def sweep_sessions(self) -> int:
        return self._claude_sessions.sweep()

    @property
    def pending_hard_restart(self) -> bool:
        return self._hard_restart

    def do_hard_restart(self) -> None:
        """Replace the gateway process so code changes take effect.

        POSIX replaces the current image. Windows starts one breakaway
        replacement and terminates the old process explicitly; its venv
        redirector cannot provide POSIX exec semantics. The lock prevents
        concurrent channel workers from launching multiple replacements.
        """
        import os
        import sys

        from ..proc import popen_detached

        with self._hard_restart_lock:
            if self._restart_origin:
                try:
                    from .. import store

                    store_module: ModuleType = store
                    if not _has_store_internals(store_module):
                        raise RuntimeError("store JSON contract is unavailable")
                    _StoreInternals.write_json(
                        store_module,
                        _restart_marker_path(),
                        {
                            "channel": self._restart_origin[0],
                            "chat_id": self._restart_origin[1],
                        },
                    )
                except Exception:
                    pass
            try:
                self.shutdown()
            except Exception:
                pass
            argv = [sys.executable, "-m", "birkin", "gateway"]
            print(
                "[gateway] hard restart: re-executing `birkin gateway`…",
                flush=True,
            )
            if os.name == "nt":
                try:
                    _ = popen_detached(argv, close_fds=True)
                except OSError as exc:
                    # shutdown() already tore this process down — staying alive
                    # would leave a gutted gateway, so exit non-zero and let the
                    # supervisor restart us.
                    print(
                        "[gateway] 하드 재시작 실패: 새 게이트웨이 프로세스를 "
                        f"시작하지 못했습니다 ({exc}). 프로세스를 종료합니다.",
                        flush=True,
                    )
                    os._exit(1)
                os._exit(0)
            else:
                os.execv(sys.executable, argv)

    def take_restart_greeting(self, channel: str) -> str | None:
        """If this process just came back from a hard restart triggered on
        ``channel``, return that chat_id once (then forget it) so the channel can
        send a 'back online' greeting. Returns None otherwise."""
        n = self._restart_notice
        if isinstance(n, dict) and n.get("channel") == channel:
            self._restart_notice = None
            return str(n.get("chat_id"))
        return None

    def command_menu(self) -> list[dict[str, str]]:
        """Return the live command menu, including local overlay additions."""
        return command_menu()

    def restart_greeting(self) -> str:
        """Return the message sent after a successful process replacement."""
        return _RESTART_GREETING

    def resolve_delivery_target(
        self,
        channel: str,
        *,
        fallback: Callable[[str], _T] | None = None,
    ) -> object | None:
        """Resolve a send-only adapter before consulting a legacy target.

        Telegram and local HTTP remain owned by their existing channel paths;
        callers can pass that existing resolution as ``fallback``. Keeping the
        registry lookup here gives outbound gateway integrations one stable
        Birkin-native seam without changing either legacy implementation.
        """
        from .channels import registry

        registry_module: ModuleType = registry
        if not _has_delivery_registry_contract(registry_module):
            raise RuntimeError("delivery registry contract is unavailable")
        return registry_module.resolve_delivery_target(
            channel, self.cfg, fallback=fallback
        )

    def interrupt(self, channel: str, chat_id: str) -> bool:
        """Cancel the turn currently in flight for this chat, if any. Called by
        a channel when a NEW message arrives mid-turn. Returns True if a turn
        was signalled. Safe to call from a different thread than handle()."""
        with self._inflight_lock:
            owners = tuple(self._inflight.get((channel, str(chat_id)), ()))
            for _token, _sess, interrupted_event in owners:
                interrupted_event.set()
        interrupted = False
        seen_sessions: set[int] = set()
        for _token, sess, _interrupted_event in reversed(owners):
            session_id = id(sess)
            if session_id in seen_sessions:
                continue
            seen_sessions.add(session_id)
            if not isinstance(sess, _InterruptibleSession):
                continue
            try:
                interrupted = sess.interrupt() or interrupted
            except Exception:
                continue
        return interrupted

    def handle(
        self,
        channel: str,
        chat_id: str,
        text: str,
        on_text: TextCallback = None,
        workflow_id: str | None = None,
        on_progress: ProgressCallback = None,
        sender_id: str | None = None,
    ) -> str:
        """Route one inbound message through the gateway turn stages."""
        from .turn_router import route_turn

        return route_turn(
            self,
            channel,
            chat_id,
            text,
            on_text,
            workflow_id,
            on_progress,
            sender_id,
        )

    def _models_command(self, arg: str) -> str:
        """List the gateway model, or select one and schedule a hard restart so the
        new model takes effect (the gateway's model is fixed at process start).
        Called under the lock."""
        parts = (arg or "").strip().split()
        provider_value = self.cfg.get("provider", "")
        provider = provider_value if isinstance(provider_value, str) else ""
        known = _gateway_model_choices(provider, self.cfg)
        listing = "\n".join(f"{i}. {model}" for i, model in enumerate(known, 1))
        if not parts:
            kind = "CLI" if provider.endswith("-cli") else "API"
            auth = "계정 로그인" if kind == "CLI" else "API key"
            lines = [
                f"현재 게이트웨이 모델: {self.cfg.get('model')} [{provider}]",
                f"연결 방식: {kind} ({auth})",
                f"사용 가능 - {kind} 모델 ({provider}):",
                listing,
                "모델 선택: /models <번호>  예: /models 1",
            ]
            return "\n".join(lines)
        name = _numbered_choice(parts[0], known)
        if not _gateway_model_accepted(provider, name, known):
            return (
                f"'{parts[0]}'은(는) 모르는 모델이에요. "
                "사용 가능한 번호는 /models에서 확인하세요."
            )
        cfg: GatewayConfig = config.load_config()
        cfg["gateway_model"] = name
        _ = config.save_config(cfg)
        # Keep in-memory state consistent even if the scheduled re-exec never
        # happens (os.execv raises) — otherwise self.cfg would report the old
        # model. The live model only actually changes on the next process start.
        self.cfg = {**self.cfg, "gateway_model": name, "model": name}
        self._hard_restart = True  # the channel re-execs after sending this reply
        print(f"[gateway] model → {name}; scheduling hard restart", flush=True)
        return (
            f"✅ 게이트웨이 모델을 '{name}'로 바꿨어요. 적용하려고 지금 재시작합니다 "
            f"— 잠시 후 다시 말 걸어주세요."
        )

    def _effort_command(self, arg: str) -> str:
        if self.cfg.get("provider") != "codex-cli":
            return "Effort 설정은 codex-cli에서만 사용할 수 있어요."
        value = (arg or "").strip().split()[0] if (arg or "").strip() else ""
        listing = "\n".join(
            f"{i}. {level}" for i, level in enumerate(_CODEX_REASONING_EFFORTS, 1)
        )
        if not value:
            current = self.cfg.get("gateway_reasoning_effort") or "default"
            return (
                f"현재 effort: {current}\n{listing}\n"
                "변경: /effort <번호>  예: /effort 2"
            )
        effort = _numbered_choice(value, _CODEX_REASONING_EFFORTS)
        if effort not in _CODEX_REASONING_EFFORTS:
            return "모르는 effort예요. /effort에서 번호를 확인하세요."
        stored_effort = "" if effort == "default" else effort
        cfg: GatewayConfig = config.load_config()
        cfg["gateway_reasoning_effort"] = stored_effort
        _ = config.save_config(cfg)
        self.cfg = {**self.cfg, "gateway_reasoning_effort": stored_effort}
        self._hard_restart = True
        print(f"[gateway] effort → {effort}; scheduling hard restart", flush=True)
        return (
            f"✅ Gateway effort를 '{effort}'로 바꿨어요. "
            "적용하려고 지금 재시작합니다 — 잠시 후 다시 말 걸어주세요."
        )

    # -- remote approvals (P0-2: the propose->approve loop, from chat) -------

    def pending_actions(self) -> list[dict[str, object]]:
        """Pending proposals, highest-risk first (same order as the CLI)."""
        from .. import risk

        risk_module: ModuleType = risk
        if not _has_risk_contract(risk_module):
            raise RuntimeError("risk sorting contract is unavailable")
        pending: list[dict[str, object]] = store.list_pending()
        records = risk_module.sort_by_risk(pending)
        return records

    def pending_text(self) -> str:
        """Plain-text pending list — the fallback for channels without
        buttons (HTTP) and the body the Telegram channel decorates."""
        from .. import approvals, risk

        risk_module: ModuleType = risk
        if not _has_risk_contract(risk_module):
            raise RuntimeError("risk sorting contract is unavailable")
        reviewable: list[dict[str, JSONValue]] = approvals.reviewable_pending()
        items = risk_module.sort_by_risk(reviewable)
        if not items:
            return "📭 No pending approvals."
        lines = [f"📋 {len(items)} pending approval(s):"]
        for rec in items[:10]:
            lines.append(
                f"- [{rec.get('category')}] {rec.get('title')} (id {rec.get('id')})"
            )
        lines.append(
            "Approve/reject in the CLI with `birkin review` — or "
            + "tap the buttons if your channel shows them."
        )
        return "\n".join(lines)

    def companion_command(self, cmd: str, arg: str, channel: str, chat_id: str) -> str:
        """``/commitment``, ``/checkin`` and ``/companion off`` from chat.

        Inspection plus the two controls that must be reachable in one step:
        pause and stop. Creating or confirming a commitment stays out of chat —
        activation needs an explicit outcome, time and source, which the CLI
        takes.
        """
        from .. import companion

        if channel != "telegram":
            return "후속 확인은 Telegram 채널에서만 설정할 수 있어요."
        context_id = f"telegram:{chat_id}"
        arg = (arg or "").strip().lower()

        if cmd == "companion":
            if arg != "off":
                return "/companion off — 후속 확인을 완전히 끕니다."
            _ = companion.pause_all()
            return "🛑 후속 확인을 껐어요. 다시 켜려면 /checkin on 을 보내 주세요."

        if cmd == "checkin":
            if arg in ("pause", "off"):
                _ = companion.pause_all()
                return "⏸ 체크인을 멈췄어요. 다시 켜려면 /checkin on."
            if arg == "on":
                _ = companion.resume()
                return "▶️ 체크인을 다시 켰어요."
            if arg and arg not in ("help", "?", "status"):
                return "/checkin · /checkin pause · /checkin on"
            companion_module: ModuleType = companion
            if not _has_companion_contract(companion_module):
                raise RuntimeError("companion contract is unavailable")
            policy = companion_module.get_policy()
            quiet = policy.get("quiet_hours", {})
            return (
                f"체크인: {'켜짐' if policy.get('enabled') else '꺼짐'}\n"
                f"시간대: {policy.get('timezone')}\n"
                f"방해 금지: {quiet.get('start')}–{quiet.get('end')}\n"
                f"하루 최대: {policy.get('daily_cap')}회"
            )

        companion_module = companion
        if not _has_companion_contract(companion_module):
            raise RuntimeError("companion contract is unavailable")
        records = [
            r
            for r in companion_module.list_commitments(context_id=context_id)
            if r["status"] in ("active", "blocked", "snoozed")
        ]
        if not records:
            return (
                "지금 따라가고 있는 약속이 없어요. "
                "`birkin companion add` 로 등록할 수 있어요."
            )
        lines: list[str] = []
        for record in records:
            lines.append(f"[{record['status']}] {record['outcome']}")
            if record.get("next_action"):
                lines.append(f"  다음 할 일: {record.get('next_action')}")
            lines.append(f"  예정: {record.get('check_in_at') or '-'}")
            lines.append(f"  출처: {record.get('source_ref') or '-'}")
        return "\n".join(lines)

    def remind_command(self, arg: str, channel: str, chat_id: str) -> str:
        """Schedule a daily prompt reminder delivered to THIS chat (P2-3).

        ``/remind 09:00 <what to do>`` · ``/remind list`` · ``/remind del <id>``.
        Only prompt-type jobs delivered to the current (already-trusted) chat
        are created — never shell, never another chat — so this cannot launder
        code execution or exfiltrate to a stranger. Callers gate on a trusted
        channel first (remind is in PRIVILEGED_COMMANDS)."""
        from .. import cron

        _ = channel
        arg = (arg or "").strip()
        if not arg or arg.lower() in ("list", "ls"):
            jobs = [
                j for j in cron.load_jobs() if str(j.get("deliver_chat_id")) == chat_id
            ]
            if not jobs:
                return "등록된 리마인더가 없어요. 예: /remind 09:00 오늘 할 일 정리해줘"
            lines = ["⏰ 리마인더:"]
            for j in jobs:
                lines.append(
                    f"- {cron.schedule_display(j)} "
                    + f"{j.get('value', '')[:60]} (id {j['id']})"
                )
            lines.append("삭제: /remind del <id>")
            return "\n".join(lines)
        parts = arg.split(maxsplit=1)
        if parts[0].lower() in ("del", "delete", "rm") and len(parts) > 1:
            aid = parts[1].strip()
            job = next((j for j in cron.load_jobs() if j.get("id") == aid), None)
            if not job or str(job.get("deliver_chat_id")) != chat_id:
                return "그 id의 리마인더를 찾지 못했어요 (본인 것만 삭제 가능)."
            try:
                _ = cron.remove_job(aid)
            except store.FileLockTimeout:
                return "⚠ 리마인더 저장소가 사용 중입니다. 잠시 후 다시 시도해 주세요."
            return f"🗑️ 리마인더 삭제됨 (id {aid})."
        # Richer schedules first ("every 30m ...", "2h ...", "0 9 * * 1 ..."),
        # then the original HH:MM / HH시MM form.
        spec, prompt = _split_schedule(arg)
        if spec is None:
            m = re.match(r"(\d{1,2})[:시](\d{2})?\s+(.+)", arg, re.S)
            if not m:
                return (
                    "형식: /remind <시각|주기> <할 일>. 예: /remind 09:00 "
                    "오늘 할 일 정리 · /remind 30분마다 메일 확인 · "
                    "/remind 1시간 후 스트레칭 · /remind 매주 월요일 09:00 "
                    "주간 리뷰 (every 30m · 2h · 0 9 * * 1 도 됩니다)"
                )
            hour = int(m.group(1))
            minute = int(m.group(2) or 0)
            if hour > 23 or minute > 59:
                # reject rather than silently clamp — 25:99 shouldn't become 23:59
                return f"시간이 올바르지 않아요 ({hour:02d}:{minute:02d}). 00:00–23:59 범위로 다시 보내 주세요."
            spec, prompt = (
                {
                    "kind": "daily",
                    "hour": hour,
                    "minute": minute,
                    "display": f"{hour:02d}:{minute:02d} daily",
                },
                m.group(3).strip(),
            )
        if not prompt:
            return "할 일을 함께 적어 주세요. 예: /remind 30분마다 메일 확인"
        try:
            job = cron.add_job(
                name="remind",
                action_type="prompt",
                value=prompt,
                deliver_chat_id=chat_id,
                schedule=spec,
            )
        except store.FileLockTimeout:
            return "⚠ 리마인더 저장소가 사용 중입니다. 잠시 후 다시 시도해 주세요."
        except ValueError as exc:
            return f"스케줄을 이해하지 못했어요: {exc}"
        return (
            f"⏰ {cron.schedule_display(job)}에 알려드릴게요: "
            f'"{prompt[:60]}" (id {job["id"]}, 취소는 /remind del {job["id"]})'
        )

    def resolve_action(
        self,
        aid: str,
        approve: bool,
        *,
        actor_id: str,
        via: str,
    ) -> str:
        """Approve/reject one pending action (the button-tap handler).
        Callers must gate on a trusted channel first."""
        from .. import approvals

        if approve:
            out = approvals.approve(
                aid,
                approved_by=actor_id,
                approved_via=via,
            )
            if not out.get("ok"):
                return f"⚠ {out.get('error', 'approve failed')}"
            store.append_activity(f"approval[{aid}]: approved via gateway")
            return f"✅ approved — {out.get('result', '')}"[:500]
        out = approvals.reject(
            aid,
            rejected_by=actor_id,
            rejected_via=via,
        )
        if not out.get("ok"):
            return "⚠ not found or already resolved"
        store.append_activity(f"approval[{aid}]: rejected via gateway")
        return "❌ rejected"

    def deny_command(self, arg: str, *, actor_id: str, via: str) -> str:
        """/deny <id> <reason> — refuse, and tell the agent why."""
        from .. import approvals

        parts = (arg or "").strip().split(None, 1)
        if not parts:
            return "형식: /deny <id> <이유>  (대기 목록은 /pending)"
        aid, reason = parts[0], (parts[1] if len(parts) > 1 else "")
        out = approvals.reject(
            aid,
            reason=reason,
            rejected_by=actor_id,
            rejected_via=via,
        )
        if not out.get("ok"):
            return "⚠ not found or already resolved"
        store.append_activity(
            f"approval[{aid}]: rejected via gateway"
            + (f" — {reason[:120]}" if reason else "")
        )
        return (
            "❌ 거부했습니다."
            if not reason
            else f"❌ 거부했습니다 — 사유를 에이전트에게 전달합니다: {reason[:200]}"
        )

    def claim_action(
        self,
        aid: str,
        *,
        actor_id: str,
        via: str,
    ) -> tuple[str, bool]:
        from .. import approvals
        out = approvals.claim(
            aid,
            approved_by=actor_id,
            approved_via=via,
        )
        if not out.get("ok"):
            return f"⚠ {out.get('error', 'approve failed')}", False
        return "✅ approved — 실행 중", True

    def execute_claimed_action(
        self, aid: str, on_progress: ProgressCallback = None
    ) -> str:
        from .. import approvals

        # moirai.phase carries what an approved hard task is doing right
        # now ("할 일 3/7: ..."); mapping it into the progress holder is
        # what turns a synchronous approval into a live heartbeat.
        _seen = {"n": 0}

        def _on_event(event: str, payload: dict[str, object]) -> None:
            if event != "moirai.phase" or on_progress is None:
                return
            _seen["n"] += 1
            try:
                on_progress(
                    {
                        "phase": str((payload or {}).get("title") or ""),
                        "activity": _seen["n"],
                    }
                )
            except Exception:
                pass  # an observer bug must not kill the action

        out = approvals.execute_claimed(
            aid, on_event=_on_event if on_progress is not None else None
        )
        if not out.get("ok"):
            return f"⚠ {out.get('error', 'approve failed')}"
        store.append_activity(f"approval[{aid}]: approved via gateway")
        return f"✅ approved — {out.get('result', '')}"[:500]

    def restore_action_claim(self, aid: str) -> None:
        from .. import approvals

        _ = approvals.restore_claim(aid)

    def _record_failed_turn(
        self,
        display_text: str,
        reply: str,
        channel: str,
        chat_id: str,
    ) -> None:
        if not self._command_trusted(channel):
            return
        TurnContract.record_turn(
            self.session,
            display_text,
            reply or "",
            review_skills=self._command_trusted(channel),
            session_id=conversation_session_id(channel, chat_id),
        )

    def _autosave_trusted(self, channel: str) -> bool:
        """Whether turns from ``channel`` may be auto-saved + memorized.

        Public channels fail closed. Telegram preserves its existing chat
        allowlist; other public adapters require an explicit sender allowlist.
        """
        normalized = str(channel or "").strip().lower()
        if normalized in _LOCAL_TRUSTED_CHANNELS:
            return True
        settings = self._channel_settings(normalized)
        if normalized == "telegram":
            return bool(settings.get("allowed_chat_ids"))
        return bool(settings.get("allowed_sender_ids"))

    def _channel_trusted(
        self, channel: str, chat_id: str, sender_id: str | None = None
    ) -> bool:
        """Authorize one inbound channel principal before any dispatch."""
        normalized = str(channel or "").strip().lower()
        if normalized in _LOCAL_TRUSTED_CHANNELS:
            return True
        settings = self._channel_settings(normalized)
        sender = str(sender_id or "").strip()
        sender_values = settings.get("allowed_sender_ids")
        allowed_senders = {
            str(value).strip()
            for value in (sender_values if isinstance(sender_values, list) else [])
            if str(value).strip()
        }
        if normalized == "telegram":
            chat_values = settings.get("allowed_chat_ids")
            allowed_chats = {
                str(value).strip()
                for value in (chat_values if isinstance(chat_values, list) else [])
                if str(value).strip()
            }
            if not allowed_chats:
                # Claude/native public turns are stripped of memory, harness,
                # review persistence, MCP, and native tools. Codex app-server
                # cannot provide an equivalent tool-free child, so it fails
                # closed unless the chat is explicitly allowlisted.
                return self.cfg.get("provider") != "codex-cli"
            if str(chat_id).strip() not in allowed_chats:
                return False
            return not allowed_senders or sender in allowed_senders
        return bool(sender and sender in allowed_senders)

    def _command_trusted(self, channel: str) -> bool:
        """Whether a channel has an explicit trusted-principal policy."""
        return self._autosave_trusted(channel)

    def _channel_settings(self, channel: str) -> dict[str, JSONValue]:
        channels = self.cfg.get("channels")
        if not isinstance(channels, dict):
            return {}
        settings = channels.get(channel)
        if not isinstance(settings, dict):
            return {}
        return {str(key): value for key, value in settings.items()}

    def _omo_command_trusted(self, channel: str, chat_id: str) -> bool:
        """Require an explicit Telegram allow-list for local OMO control."""
        if channel != "telegram":
            return False
        telegram = self._channel_settings("telegram")
        allowed = telegram.get("allowed_chat_ids")
        return isinstance(allowed, list) and str(chat_id) in {
            str(value) for value in allowed
        }


def run() -> int:
    install_timestamped_logging()
    from ..approval_execution_recovery import recover_all

    _ = recover_all()
    # Anything still `running` when this process boots belongs to a process
    # that is gone — leaving it makes a crashed run indistinguishable from a
    # live one.
    from ..moirai import continuation as moirai_continuation
    from ..moirai import journal as moirai_journal

    stale = moirai_journal.reclaim_stale_runs(
        exclude=moirai_continuation.protected_run_ids()
    )
    if stale:
        print(f"[gateway] moirai: {stale} stale run(s) reclaimed", flush=True)
    _ = moirai_continuation.recover()
    cfg: GatewayConfig = config.load_config()
    # Advisory (never blocking): make native-loop tool exposure visible
    # before the gateway becomes reachable over a channel.
    security.print_gateway_warnings(cfg)
    try:
        gateway = Gateway(cfg)
    except ConfigError as exc:
        print(f"{exc}")
        return 1
    except TelegramGatewayOwnedError as exc:
        print(
            "[gateway] 다른 birkin 게이트웨이가 같은 텔레그램 봇을 이미 사용 중입니다 "
            f"(소유 PID {exc.owner_pid}). 잠금 파일: {exc.path}"
        )
        return 1
    except TelegramGatewayLeaseRaceError as exc:
        print(
            "[gateway] 텔레그램 소유권을 확보하지 못했습니다. 잠금 파일을 확인한 뒤 "
            f"다시 시도해 주세요: {exc.path}"
        )
        return 1

    # Just came back from a hard re-exec? Load the one-shot marker so the channel
    # that triggered it greets that chat "I'm back". Delete it immediately.
    try:
        from .. import store

        marker = _restart_marker_path()
        store_module: ModuleType = store
        if not _has_store_internals(store_module):
            raise RuntimeError("store JSON contract is unavailable")
        notice = _StoreInternals.read_json(store_module, marker)
        if isinstance(notice, dict):
            gateway.load_restart_notice(notice)
            try:
                marker.unlink()
            except OSError:
                pass
    except Exception:
        pass

    from .channels import build_channels

    channels = build_channels(cfg)
    if not channels:
        print(
            "No channels enabled. Enable one in config.channels "
            + "(http is on by default) and retry."
        )
        return 1

    mode = "warm/persistent" if gateway.persistent else "per-message"
    gateway.prewarm()  # first message of a new conversation skips cold start
    print(
        f"birkin gateway up · model {gateway.cfg.get('model')} · {mode} · "
        + f"channels: {', '.join(c.name for c in channels)}"
    )
    print(
        "  chat commands: /help · /new · /restart (soft) · /hard_restart "
        + "— hyphens, /restart-gateway, and @bot suffix all accepted"
    )
    threads: list[threading.Thread] = []
    for ch in channels:
        t = threading.Thread(target=ch.start, args=(gateway,), daemon=True)
        t.start()
        threads.append(t)
    try:
        last_sweep = time.monotonic()
        while any(t.is_alive() for t in threads):
            for t in threads:
                t.join(timeout=0.5)
            if time.monotonic() - last_sweep >= 60:  # evict idle warm sessions
                _ = gateway.sweep_sessions()
                last_sweep = time.monotonic()
    except KeyboardInterrupt:
        print("\ngateway stopping…")
    finally:
        gateway.shutdown()
    return 0
