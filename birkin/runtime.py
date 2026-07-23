"""Wire the pieces together into a ready-to-use session.

Both the CLI REPL and the WebUI build a ``Session`` from here, so the agent is
configured identically in either surface.
"""

from __future__ import annotations

import copy
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from . import budget, checkpoints, config, hooks, promptgate, store
from .agent import Agent
from .llm import LLMClient, LLMError, build_client
from .memory import Memory
from .skills import SkillManager, build_manager
from .tools import ToolContext, build_registry


class ConfigError(RuntimeError):
    pass


@dataclass
class Session:
    cfg: dict[str, Any]
    client: LLMClient
    skills: SkillManager
    memory: Memory
    ctx: ToolContext
    agent: Agent
    # Set to interrupt the in-flight turn (Esc in the REPL); cleared before each
    # ask(). Threaded into agent.run -> the LLM stream / CLI subprocess.
    abort: threading.Event = field(default_factory=threading.Event)
    # Opt-in warm CLI session (repl_warm_session): one long-lived claude/codex
    # process reused across turns, so the REPL stops paying the ~10 s CLI cold
    # start every message (matching the gateway). Lazy; None until first use.
    _warm: Any = None
    _warm_skill_state: dict[str, Any] = field(
        default_factory=lambda: {"revision": -1, "names": set()})
    _skill_review_turns: int = 0
    _skill_review_thread: threading.Thread | None = None
    _skill_review_lock: Any = field(default_factory=threading.Lock)
    _memory_review_transcripts: list[str] = field(default_factory=list)

    def refresh_system_prompt(self) -> None:
        """Rebuild the system prompt to reflect current skills/memory/persona.

        The persona (``SOUL.md``) is read fresh each turn so edits — and
        ``/personality`` swaps — take effect with no restart."""
        self.agent.system = promptgate.compose_main(
            self.cfg, skills_index=self.skills.index(),
            memory_block=self.memory.render())

    def _build_cli_system(self, text: str) -> None:
        """For CLI-agent backends: inject identity + memory + skills routed to
        the request (they can't call load_skill themselves)."""
        preloaded = self._route_cli_skills(text)
        self.agent.system = promptgate.compose_cli(
            self.cfg, memory_block=self.memory.render(),
            preloaded=preloaded or None)

    def _route_cli_skills(self, text: str,
                          loaded_skills: set[str] | None = None) -> list[str]:
        from .curator import record_use
        routed = self.skills.route(text, limit=3)
        for skill in routed:
            record_use(skill.name)
        fresh = [skill for skill in routed
                 if loaded_skills is None or skill.name not in loaded_skills]
        if loaded_skills is not None:
            loaded_skills.update(skill.name for skill in routed)
        return [self.skills.render_skill(skill) for skill in fresh]

    def _prepare_cli_turn(self, text: str, *, route_query: str | None = None,
                          skill_state: dict[str, Any] | None = None) -> str:
        self.skills.reload_if_changed(debounce=0.0)
        loaded_skills = None
        if skill_state is not None:
            loaded_skills = skill_state["names"]
            if skill_state["revision"] != self.skills.revision:
                loaded_skills.clear()
                skill_state["revision"] = self.skills.revision
        preloaded = self._route_cli_skills(
            text if route_query is None else route_query, loaded_skills)
        if not preloaded:
            return text
        return ("## Birkin routed skills for this turn\n\n"
                + "\n\n".join(preloaded)
                + "\n\n## User request\n\n" + text)

    def ask(self, text: str,
            on_text: Optional[Callable[[str], None]] = None, *,
            review_skills: bool = True,
            route_query: str | None = None,
            record_turn: bool = True) -> str:
        # Budget gate — refuse with a clear message instead of silently spending.
        over, why = budget.is_over(self.cfg)
        if over:
            if record_turn:
                store.save_run("chat", "skipped: over-budget",
                               details={"provider": self.cfg.get("provider"),
                                        "model": self.cfg.get("model"),
                                        "blocked_by": "budget"},
                               usage=store.estimate_usage(text))
            return why
        self.skills.reload_if_changed()  # pick up edited/added skills live
        self.abort.clear()               # fresh turn — drop any stale abort
        if self.ctx.checkpoints is not None:
            self.ctx.checkpoints.new_turn()
            if (self._use_warm()
                    or self.cfg.get("provider") in config.CLI_PROVIDERS):
                # A CLI provider's child process edits files with its own
                # tools, which never reach our registry — so the only
                # chance to snapshot is here, before the turn starts.
                self.ctx.checkpoints.ensure_checkpoint(
                    self.ctx.cwd, "before CLI turn")
        if self._use_warm():
            reply = self._warm_ask(text, on_text)
            if record_turn:
                self._record_turn(text, reply, review_skills=review_skills)
            return reply
        if self.cfg.get("provider") in config.CLI_PROVIDERS:
            self._build_cli_system(
                text if route_query is None else route_query)
        else:
            self.refresh_system_prompt()
        reply = self.agent.run(text, on_text=on_text, abort=self.abort)
        if record_turn:
            self._record_turn(text, reply, review_skills=review_skills)
        return reply

    def steer(self, text: str) -> bool:
        """Send an instruction into the turn already running, without killing it.

        Returns False when this session cannot be steered, which tells the
        caller to fall back to interrupting.
        """
        if self._warm is not None:
            steer = getattr(self._warm, "steer", None)
            return bool(steer(text)) if steer else False
        return self.agent.steer(text)

    def _use_warm(self) -> bool:
        """Opt-in warm CLI session, for claude-cli/codex-cli only. Trades the
        per-turn skill routing for a gateway-style skill index fixed at process
        start, and Esc-to-interrupt for a faster turn — hence off by default."""
        return (bool(self.cfg.get("repl_warm_session"))
                and self.cfg.get("provider") in ("claude-cli", "codex-cli"))

    def _warm_ask(self, text: str,
                  on_text: Optional[Callable[[str], None]]) -> str:
        if self._warm is None:
            self._warm = self._build_warm()
        return self._warm.ask(
            self._prepare_cli_turn(text, skill_state=self._warm_skill_state),
            on_text=on_text)

    def _build_warm(self):
        """One warm session carrying persona + memory + skill index (the same
        snapshot the gateway uses). The process keeps conversation context, so
        only the new turn is sent each ask()."""
        try:
            idx = self.skills.index()
        except Exception:
            idx = ""
        extra = ("\n\n## birkin skills available\n"
                 "Read the referenced SKILL.md with your own file tools to "
                 "follow one when it fits the task.\n" + idx) if idx else ""
        system = promptgate.compose_cli(
            self.cfg, memory_block=self.memory.render(), extra=extra)
        if self.cfg.get("provider") == "codex-cli":
            from .codex_session import CodexAppServerSession
            sandbox = ("danger-full-access"
                       if self.cfg.get("cli_access") == "full"
                       else "workspace-write")
            return CodexAppServerSession(model=self.cfg.get("model"),
                                         preamble=system, sandbox_mode=sandbox,
                                         approval_policy="never")
        from .claude_session import ClaudeStreamSession
        return ClaudeStreamSession(
            model=self.cfg.get("model"),
            cli_access=self.cfg.get("cli_access", "workspace"),
            append_system_prompt=system)

    def close(self) -> None:
        """Release the warm session's subprocess, if any (REPL shutdown)."""
        if self._warm is not None:
            try:
                self._warm.close()
            except Exception:
                pass
            self._warm = None
        self._warm_skill_state = {"revision": -1, "names": set()}

    def _record_turn(self, text: str, reply: str, *,
                     review_skills: bool = True) -> None:
        """Write an auditable run record (+ ledger line + usage) per chat turn."""
        try:
            usage = store.estimate_usage(self.agent.system, text, reply or "")
            body = (reply or "").strip()
            summary = body.splitlines()[0][:160] if body else "(no reply)"
            store.save_run("chat", summary, details={
                "provider": self.cfg.get("provider"),
                "model": self.cfg.get("model"),
                "tools": list(self.agent.last_tools),
                "iterations": self.agent.last_iterations,
            }, usage=usage)
        except Exception:
            pass  # auditing must never break a chat turn
        if review_skills:
            self._schedule_skill_review(text, reply)

    def _schedule_skill_review(self, text: str, reply: str) -> None:
        provider = self.cfg.get("provider")
        if (provider not in ("claude-cli", "codex-cli")
                or not self.cfg.get("self_improve", True)
                or budget.is_over(self.cfg)[0]):
            return
        interval_key = ("memory_nudge_interval" if provider == "codex-cli"
                        else "skill_nudge_interval")
        interval = int(self.cfg.get(interval_key, 6 if provider == "codex-cli"
                                    else 3))
        if interval <= 0:
            return
        transcript = f"USER:\n{text}\n\nASSISTANT:\n{reply}"
        with self._skill_review_lock:
            self._skill_review_turns += 1
            if provider == "codex-cli":
                self._memory_review_transcripts.append(transcript)
            if self._skill_review_turns < interval:
                return
            if (self._skill_review_thread
                    and self._skill_review_thread.is_alive()):
                return
            self._skill_review_turns = 0
            review_transcript = ("\n\n".join(self._memory_review_transcripts)
                                 if provider == "codex-cli" else transcript)
            review_kind = ("memory-review" if provider == "codex-cli"
                           else "skill-review")
            review_ctx = copy.copy(self.ctx)
            review_ctx.cfg = dict(self.ctx.cfg)
            review_ctx.client = copy.copy(self.ctx.client)
            review_model = self.cfg.get("model")

            def review() -> None:
                from .selfimprove import reflect_and_learn, review_cli_turn
                try:
                    if provider == "codex-cli":
                        summary = reflect_and_learn(review_ctx, review_transcript)
                    else:
                        summary = review_cli_turn(review_ctx, review_transcript)
                except LLMError as exc:
                    summary = f"{review_kind} failed: {exc}"
                store.save_run(review_kind, summary, details={
                    "provider": provider,
                    "model": review_model,
                }, usage=store.estimate_usage(review_transcript, summary))

            try:
                self._skill_review_thread = threading.Thread(
                    target=review, name=f"birkin-{review_kind}", daemon=True)
                self._skill_review_thread.start()
                if provider == "codex-cli":
                    self._memory_review_transcripts.clear()
            except (OSError, RuntimeError):
                self._skill_review_thread = None
                self._skill_review_turns = interval - 1

    def new_conversation(self) -> None:
        self.agent.reset()
        self._skill_review_turns = 0
        self._memory_review_transcripts.clear()
        # The warm session keeps its OWN conversation context in the child
        # process, so /new must drop it or the model still remembers the prior
        # turns despite "Started a new conversation."
        self.close()

    def reload_client(self) -> None:
        """Rebuild the LLM client from ``self.cfg`` so a ``/model`` / ``/models``
        change — even one that switches provider (API <-> a local CLI agent) —
        takes effect on this live session with no restart. Rewires the client on
        the session, the tool context (for subagents), and the agent."""
        api_key = config.get_api_key(self.cfg) or ""
        self.client = build_client(self.cfg, api_key)
        self.ctx.client = self.client
        self.agent.client = self.client
        self.agent.model = self.cfg.get("model")
        with self._skill_review_lock:
            self._skill_review_turns = 0
            self._memory_review_transcripts.clear()
        # The warm CLI process baked the OLD --model at spawn; drop it so the
        # next warm ask() respawns with the new model/provider.
        self.close()


def build_session(cfg: Optional[dict[str, Any]] = None,
                  on_event: Optional[Callable[[str, dict[str, Any]], None]] = None
                  ) -> Session:
    cfg = cfg or config.load_config()
    api_key = config.get_api_key(cfg)
    if not api_key:
        provider = cfg.get("provider", "anthropic")
        if provider in config.OAUTH_PROVIDERS:
            raise ConfigError(
                "Not logged in to Claude. Run `claude /login` (or "
                "`claude setup-token`) so birkin can use your Claude "
                "subscription, then retry. No API key is needed.")
        env = config.PROVIDER_API_KEY_ENV.get(provider, "ANTHROPIC_API_KEY")
        raise ConfigError(
            f"No API key found. Set the {env} environment variable, "
            f"or run `birkin setup`.")

    client = build_client(cfg, api_key)
    skills = build_manager(cfg)
    memory = Memory(cfg)
    checkpoint_mgr = checkpoints.CheckpointManager(
        enabled=bool(cfg.get("checkpoints", True)),
        keep=int(cfg.get("checkpoint_keep", 20)))
    hook_bus = hooks.build_bus(cfg)
    ctx = ToolContext(
        cfg=cfg, client=client, cwd=Path.cwd(),
        skills=skills, memory=memory,
        max_depth=int(cfg.get("max_depth", 2)), emit=on_event,
        checkpoints=checkpoint_mgr, hooks=hook_bus)
    registry = build_registry(ctx)
    system = promptgate.compose_main(
        cfg, skills_index=skills.index(), memory_block=memory.render())
    agent = Agent(client=client, system=system, registry=registry,
                  max_turns=int(cfg.get("max_turns", 24)),
                  model=cfg.get("model"), on_event=on_event,
                  self_improve=bool(cfg.get("self_improve", True)),
                  skill_nudge_interval=int(cfg.get("skill_nudge_interval", 3)),
                  memory_nudge_interval=int(cfg.get("memory_nudge_interval", 6)),
                  auto_compact=bool(cfg.get("auto_compact", True)),
                  context_window=int(cfg.get("context_window", 200000)),
                  parallel_tools=bool(cfg.get("parallel_tools", True)),
                  parallel_workers=int(cfg.get("parallel_tool_workers", 8)),
                  hooks=hook_bus)
    return Session(cfg=cfg, client=client, skills=skills, memory=memory,
                   ctx=ctx, agent=agent)


def build_dry_run_packet(text: str, cfg: Optional[dict[str, Any]] = None
                         ) -> dict[str, Any]:
    """Assemble the exact prompt packet for `text` WITHOUT any model call or API
    key — the system prompt, tool names (or routed skills for CLI providers),
    and a usage estimate. Powers `birkin chat --dry-run`."""
    cfg = cfg or config.load_config()
    provider = cfg.get("provider", "anthropic")
    skills = build_manager(cfg)
    memory = Memory(cfg)

    if provider in config.CLI_PROVIDERS:
        routed = skills.route(text, limit=3)
        system = promptgate.compose_cli(
            cfg, memory_block=memory.render(),
            preloaded=[skills.render_skill(s) for s in routed] or None)
        tool_names: list[str] = []
        routed_names = [s.name for s in routed]
    else:
        ctx = ToolContext(cfg=cfg, client=None, cwd=Path.cwd(), skills=skills,
                          memory=memory, max_depth=int(cfg.get("max_depth", 2)))
        system = promptgate.compose_main(
            cfg, skills_index=skills.index(), memory_block=memory.render())
        tool_names = [t["name"] for t in build_registry(ctx).specs()]
        routed_names = []

    return {
        "provider": provider,
        "model": cfg.get("model"),
        "system": system,
        "tools": tool_names,
        "routed_skills": routed_names,
        "user": text,
        "usage": store.estimate_usage(system, text),
    }
