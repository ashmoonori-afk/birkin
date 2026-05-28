"""Wire the pieces together into a ready-to-use session.

Both the CLI REPL and the WebUI build a ``Session`` from here, so the agent is
configured identically in either surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from . import budget, config, prompts, store
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

    def refresh_system_prompt(self) -> None:
        """Rebuild the system prompt to reflect current skills/memory."""
        self.agent.system = prompts.build_system_prompt(
            skills_index=self.skills.index(),
            memory_block=self.memory.render())

    def _build_cli_system(self, text: str) -> None:
        """For CLI-agent backends: inject identity + memory + skills routed to
        the request (they can't call load_skill themselves)."""
        routed = self.skills.route(text, limit=3)
        preloaded = [self.skills.render_skill(s) for s in routed]
        self.agent.system = prompts.build_cli_system(
            memory_block=self.memory.render(), preloaded=preloaded or None)

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
        if self.cfg.get("provider") in config.CLI_PROVIDERS:
            self._build_cli_system(text)
        else:
            self.refresh_system_prompt()
        reply = self.agent.run(text, on_text=on_text)
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


def build_session(cfg: Optional[dict[str, Any]] = None,
                  on_event: Optional[Callable[[str, dict[str, Any]], None]] = None
                  ) -> Session:
    cfg = cfg or config.load_config()
    api_key = config.get_api_key(cfg)
    if not api_key:
        provider = cfg.get("provider", "anthropic")
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
    system = prompts.build_system_prompt(
        skills_index=skills.index(), memory_block=memory.render())
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
        system = prompts.build_cli_system(
            memory_block=memory.render(),
            preloaded=[skills.render_skill(s) for s in routed] or None)
        tool_names: list[str] = []
        routed_names = [s.name for s in routed]
    else:
        ctx = ToolContext(cfg=cfg, client=None, cwd=Path.cwd(), skills=skills,
                          memory=memory, max_depth=int(cfg.get("max_depth", 2)))
        system = prompts.build_system_prompt(
            skills_index=skills.index(), memory_block=memory.render())
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
