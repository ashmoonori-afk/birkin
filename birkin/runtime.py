"""Wire the pieces together into a ready-to-use session.

Both the CLI REPL and the WebUI build a ``Session`` from here, so the agent is
configured identically in either surface.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from . import budget, config, promptgate, store
from .agent import Agent
from .llm import LLMClient, build_client
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
        routed = self.skills.route(text, limit=3)
        preloaded = [self.skills.render_skill(s) for s in routed]
        self.agent.system = promptgate.compose_cli(
            self.cfg, memory_block=self.memory.render(),
            preloaded=preloaded or None)

    def ask(self, text: str,
            on_text: Optional[Callable[[str], None]] = None) -> str:
        # Budget gate — refuse with a clear message instead of silently spending.
        over, why = budget.is_over(self.cfg)
        if over:
            store.save_run("chat", "skipped: over-budget",
                           details={"provider": self.cfg.get("provider"),
                                    "model": self.cfg.get("model"),
                                    "blocked_by": "budget"},
                           usage=store.estimate_usage(text))
            return why
        self.skills.reload_if_changed()  # pick up edited/added skills live
        self.abort.clear()               # fresh turn — drop any stale abort
        if self.cfg.get("provider") in config.CLI_PROVIDERS:
            self._build_cli_system(text)
        else:
            self.refresh_system_prompt()
        reply = self.agent.run(text, on_text=on_text, abort=self.abort)
        self._record_turn(text, reply)
        return reply

    def _record_turn(self, text: str, reply: str) -> None:
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

    def new_conversation(self) -> None:
        self.agent.reset()

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
    ctx = ToolContext(
        cfg=cfg, client=client, cwd=Path.cwd(),
        skills=skills, memory=memory,
        max_depth=int(cfg.get("max_depth", 2)), emit=on_event)
    registry = build_registry(ctx)
    system = promptgate.compose_main(
        cfg, skills_index=skills.index(), memory_block=memory.render())
    agent = Agent(client=client, system=system, registry=registry,
                  max_turns=int(cfg.get("max_turns", 24)),
                  model=cfg.get("model"), on_event=on_event,
                  self_improve=bool(cfg.get("self_improve", True)),
                  skill_nudge_interval=int(cfg.get("skill_nudge_interval", 3)),
                  memory_nudge_interval=int(cfg.get("memory_nudge_interval", 6)))
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
