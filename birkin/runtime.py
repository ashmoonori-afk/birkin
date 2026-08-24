"""Wire the pieces together into a ready-to-use session.

Both the CLI REPL and the WebUI build a ``Session`` from here, so the agent is
configured identically in either surface.
"""

from __future__ import annotations

import copy
import inspect
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from . import (
    budget,
    checkpoints,
    config,
    goals,
    hooks,
    promptgate,
    prompts,
    store,
)
from .agent import Agent
from .llm import LLMClient, LLMError, build_client
from .profile_actions import ProfileActions
from .profile_prompt import render_profile_blocks
from .profile_review import ProfileReviewService, build_profile_review
from .rolefiles import ProfileSnapshot, ProfileStore
from .memory import Memory
from .skills import SkillManager, build_manager
from .skills.routing import assemble_routed_skills
from .tools import ToolContext, build_registry

if TYPE_CHECKING:
    from .workspace.records import WorkspaceSnapshot


class ConfigError(RuntimeError):
    pass


def _profile_snapshot() -> ProfileSnapshot:
    return ProfileStore(config.birkin_home(), {}).snapshot()


def _profiles_enabled(cfg: dict[str, Any]) -> bool:
    profile = cfg.get("profile")
    return isinstance(profile, dict) and profile.get("enabled") is True


def _profile_block(cfg: dict[str, Any]) -> str:
    if not _profiles_enabled(cfg):
        return ""
    ProfileStore(config.birkin_home(), {}).bootstrap()
    return render_profile_blocks(_profile_snapshot())


def _profile_revision(cfg: dict[str, Any]) -> str:
    if not _profiles_enabled(cfg):
        return ""
    return _profile_snapshot().revision


def _harness_block(
    cfg: dict[str, Any],
    *,
    trusted: bool = True,
) -> str:
    """The harness summary injected into the system prompt (empty when off)."""
    if not trusted or not cfg.get("harness_enabled", True):
        return ""
    from . import harness
    current = harness.snapshot(str(cfg.get("session_id") or "default"))
    return harness.render_block(
        current["state"],
        budget=cfg.get("harness_prompt_budget"),
        revision=current["revision"],
    )


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
    # Presentation-only focus hook installed by the unified terminal workspace.
    # Slash aliases use it to change panels without starting nested UI loops.
    workspace_focus: Callable[[str], None] | None = None
    workspace_snapshot: Callable[[], WorkspaceSnapshot] | None = None
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
    _harness_turns: dict[str, int] = field(default_factory=dict)
    _harness_thread: threading.Thread | None = None
    _harness_lock: Any = field(default_factory=threading.Lock)
    _harness_transcripts: dict[str, list[str]] = field(default_factory=dict)
    # Per-session monotonic stamp of the last harness review.
    _harness_last: dict[str, float] = field(default_factory=dict)
    _checkpoint_session: list[str] = field(default_factory=list)
    _warm_profile_revision: str = ""
    _profile_notice_revisions: set[str] = field(default_factory=set)
    profile_review_service: ProfileReviewService | None = None

    def refresh_system_prompt(
        self,
        *,
        session_id: str | None = None,
        trusted: bool = True,
    ) -> None:
        """Rebuild the system prompt to reflect current skills/memory/persona.

        The persona (``SOUL.md``) is read fresh each turn so edits — and
        ``/personality`` swaps — take effect with no restart."""
        if not trusted:
            turn_cfg = (
                self.cfg
                if session_id is None
                else {**self.cfg, "session_id": session_id}
            )
            turn_cfg = {**turn_cfg, "session_goal_fallback": False}
            self.agent.system = promptgate.compose_public(
                trusted_session_state=promptgate.compose_turn_context(
                    turn_cfg
                )
            )
            return
        turn_cfg = (
            self.cfg
            if session_id is None
            else {**self.cfg, "session_id": session_id}
        )
        self.agent.system = promptgate.compose_main(
            turn_cfg,
            skills_index=self.skills.index() if trusted else "",
            memory_block=self.memory.render() if trusted else "",
            profile_block=_profile_block(turn_cfg) if trusted else "",
            harness_block=_harness_block(turn_cfg, trusted=trusted),
            include_turn_state=trusted,
            persona_text=None if trusted else "")

    def _build_cli_system(
        self,
        text: str,
        *,
        session_id: str | None = None,
        trusted: bool = True,
    ) -> None:
        """For CLI-agent backends: inject identity + memory + skills routed to
        the request (they can't call load_skill themselves)."""
        if not trusted:
            turn_cfg = (
                self.cfg
                if session_id is None
                else {**self.cfg, "session_id": session_id}
            )
            turn_cfg = {**turn_cfg, "session_goal_fallback": False}
            self.agent.system = promptgate.compose_public(
                trusted_session_state=promptgate.compose_turn_context(
                    turn_cfg
                )
            )
            return
        preloaded = self._route_cli_skills(text) if trusted else []
        extra = ""
        if trusted and not preloaded:
            # Routing is keyword overlap against skill text, which is
            # written in English — so a request in another language matches
            # nothing and the CLI child would see no skills at all. That is
            # the common case here, not an edge case: birkin's house rule
            # is 대화는 한국어. Fall back to the catalog index and let the
            # model, which is multilingual, pick. Same block the warm
            # session already carries.
            try:
                idx = self.skills.index()
            except Exception:
                idx = ""
            if idx:
                extra = ("\n\n## birkin skills available\n"
                         "Read the referenced SKILL.md with your own file "
                         "tools to follow one when it fits the task.\n" + idx)
        # Only promise the tools when they are actually attached — llm.py adds
        # the MCP server iff birkin_mcp is set, and an API-provider client has
        # no such attribute at all.
        if getattr(self.client, "birkin_mcp", False):
            extra += prompts.cli_mcp_block()
        turn_cfg = (
            self.cfg
            if session_id is None
            else {**self.cfg, "session_id": session_id}
        )
        self.agent.system = promptgate.compose_cli(
            turn_cfg,
            memory_block=self.memory.render() if trusted else "",
            profile_block=_profile_block(turn_cfg) if trusted else "",
            preloaded=preloaded or None, extra=extra,
            harness_block=_harness_block(turn_cfg, trusted=trusted),
            include_turn_state=trusted,
            persona_text=None if trusted else "")

    def _route_cli_skills(self, text: str,
                          loaded_skills: set[str] | None = None) -> list[str]:
        from .curator import record_use

        routed = assemble_routed_skills(self.skills, text, loaded_skills)
        for name in routed.names:
            record_use(name)
        if loaded_skills is not None:
            loaded_skills.update(routed.names)
        return list(routed.rendered)

    def _prepare_cli_turn(self, text: str, *, route_query: str | None = None,
                          skill_state: dict[str, Any] | None = None,
                          session_id: str | None = None,
                          trusted: bool = True) -> str:
        self.skills.reload_if_changed(debounce=0.0)
        loaded_skills = None
        if skill_state is not None:
            loaded_skills = skill_state["names"]
            if skill_state["revision"] != self.skills.revision:
                loaded_skills.clear()
                skill_state["revision"] = self.skills.revision
        preloaded = (
            self._route_cli_skills(
                text if route_query is None else route_query,
                loaded_skills,
            )
            if trusted
            else []
        )
        turn_cfg = (
            self.cfg
            if session_id is None
            else {**self.cfg, "session_id": session_id}
        )
        if not trusted:
            turn_cfg = {**turn_cfg, "session_goal_fallback": False}
        current = promptgate.compose_turn_context(
            turn_cfg, user_text=text if trusted else "")
        if trusted and turn_cfg.get("cynefin_enabled", True):
            try:
                from . import cynefin, ledger
                ledger.event("cynefin", cynefin.classify(text))
            except Exception:
                pass  # observability only -- never break a turn
        if not preloaded and not current:
            return text
        sections: list[str] = []
        if current:
            sections.append(current)
        if preloaded:
            sections.append(
                "## Birkin routed skills for this turn\n\n"
                + "\n\n".join(preloaded)
            )
        return "\n\n".join(sections) + "\n\n## User request\n\n" + text

    def ask(self, text: str,
            on_text: Optional[Callable[[str], None]] = None, *,
            review_skills: bool = True,
            route_query: str | None = None,
            record_turn: bool = True,
            session_id: str | None = None,
        trusted: bool = True) -> str:
        if self._checkpoint_session:
            self._checkpoint_session[0] = str(
                session_id
                or self.cfg.get("session_id")
                or self._checkpoint_session[0]
            )
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
        if self._use_warm() and trusted:
            reply = self._warm_ask(text, on_text, session_id=session_id)
            if record_turn:
                self._record_turn(
                    text,
                    reply,
                    review_skills=review_skills,
                    session_id=session_id,
                    review_harness=trusted,
                )
            return reply
        if self.cfg.get("provider") in config.CLI_PROVIDERS:
            self._build_cli_system(
                text if route_query is None else route_query,
                session_id=session_id,
                trusted=trusted)
        else:
            self.refresh_system_prompt(
                session_id=session_id,
                trusted=trusted,
            )
            if trusted:
                preloaded = self._route_cli_skills(
                    text if route_query is None else route_query
                )
                if preloaded:
                    self.agent.system += (
                        "\n\n## Birkin routed skills for this turn\n\n"
                        + "\n\n".join(preloaded)
                    )
        blocked_tools = (
            None
            if trusted
            else frozenset(
                str(spec.get("name", ""))
                for spec in self.agent.registry.specs()
            )
        )
        run_params = inspect.signature(self.agent.run).parameters
        accepts_kwargs = any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in run_params.values()
        )
        run_kwargs: dict[str, Any] = {}
        if accepts_kwargs or "on_text" in run_params:
            run_kwargs["on_text"] = on_text
        if accepts_kwargs or "abort" in run_params:
            run_kwargs["abort"] = self.abort
        supports_blocking = accepts_kwargs or "blocked_tools" in run_params
        supports_trust = accepts_kwargs or "trusted" in run_params
        if not trusted and (not supports_blocking or not supports_trust):
            raise ConfigError(
                "agent implementation cannot enforce untrusted turn isolation"
            )
        if supports_blocking:
            run_kwargs["blocked_tools"] = blocked_tools
        if supports_trust:
            run_kwargs["trusted"] = trusted
        reply = self.agent.run(text, **run_kwargs)
        if record_turn:
            self._record_turn(
                text,
                reply,
                review_skills=review_skills,
                session_id=session_id,
                review_harness=trusted,
            )
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

    def _warm_ask(
        self,
        text: str,
        on_text: Optional[Callable[[str], None]],
        *,
        session_id: str | None = None,
    ) -> str:
        if self._warm is None:
            self._warm = self._build_warm()
        self._emit_profile_notices(on_text, session_id=session_id)
        return self._warm.ask(
            self._prepare_cli_turn(
                text,
                skill_state=self._warm_skill_state,
                session_id=session_id,
            ),
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
        profile_block = ""
        self._warm_profile_revision = ""
        if _profiles_enabled(self.cfg):
            ProfileStore(config.birkin_home(), {}).bootstrap()
            snapshot = _profile_snapshot()
            self._warm_profile_revision = snapshot.revision
            profile_block = render_profile_blocks(snapshot)
        system = promptgate.compose_cli(
            self.cfg, memory_block=self.memory.render(), extra=extra,
            profile_block=profile_block,
            harness_block=_harness_block(self.cfg),
            include_turn_state=False)
        if self.cfg.get("provider") == "codex-cli":
            from .codex_session import CodexAppServerSession
            sandbox = ("danger-full-access"
                       if self.cfg.get("cli_access") == "full"
                       else "workspace-write")
            return CodexAppServerSession(model=self.cfg.get("model"),
                                         preamble=system, sandbox_mode=sandbox,
                                         approval_policy="never",
                                         network_access=(
                                             sandbox == "workspace-write"
                                             and self.cfg.get(
                                                 "cli_network_access", False)
                                             is True))
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
        self._warm_profile_revision = ""
        self._profile_notice_revisions.clear()

    def _emit_profile_notices(
        self,
        on_text: Optional[Callable[[str], None]],
        *,
        session_id: str | None = None,
    ) -> None:
        current = _profile_revision(self.cfg)
        if (self._warm_profile_revision
                and current != self._warm_profile_revision
                and current not in self._profile_notice_revisions):
            self._profile_notice_revisions.add(current)
            if on_text is not None:
                on_text("profile updated - /new required")
        service = self.profile_review_service
        if service is not None:
            for notice in service.drain_notices(
                str(session_id or self.cfg.get("session_id") or "")
            ):
                if on_text is not None:
                    on_text(notice)

    def _record_turn(
        self,
        text: str,
        reply: str,
        *,
        review_skills: bool = True,
        session_id: str | None = None,
        review_harness: bool = True,
    ) -> None:
        """Write an auditable run record (+ ledger line + usage) per chat turn."""
        input_usage = store.estimate_usage(self.agent.system, text)["estTokens"]
        output_usage = store.estimate_usage(reply or "")["estTokens"]
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
        except Exception as exc:
            print(f"[birkin] warning: could not save run record: {exc}",
                  file=sys.stderr, flush=True)
        try:
            usage_session = (
                session_id
                if session_id is not None
                else str(self.cfg["session_id"])
            )
            updated_goal = goals.add_usage(
                input_usage,
                output_usage,
                session_id=usage_session,
            )
            if (updated_goal is None and session_id is None
                    and self.cfg.get("session_goal_fallback", True)):
                goals.add_usage(input_usage, output_usage)
        except Exception as exc:
            print(f"[birkin] warning: could not update goal usage: {exc}",
                  file=sys.stderr, flush=True)
        service = self.profile_review_service
        if service is not None:
            try:
                service.record_exchange(
                    text,
                    reply or "",
                    trusted=review_harness,
                    session_id=str(session_id or self.cfg.get("session_id") or "default"),
                )
            except Exception:
                pass
        if self.cfg.get("evidence_gate_enabled", False):
            try:
                # Ladder-of-inference gate (design item 3): observe-only --
                # score the reply's claims against this session's tool
                # outputs and record the counts; never touch the reply.
                from . import evidence_gate, ledger
                outputs = evidence_gate.collect_tool_outputs(
                    getattr(self.agent, "messages", []) or [])
                report = evidence_gate.verify_reply(reply or "", outputs)
                ledger.event(
                    "evidence_gate",
                    f"supported={report.supported_count} "
                    f"unsupported={len(report.unsupported)}")
            except Exception:
                pass  # observe-only -- never break a turn
        if review_skills:
            self._schedule_skill_review(text, reply)
        if review_harness:
            self._schedule_harness_review(
                text, reply, session_id=session_id
            )

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
        failures = failure_context()
        if failures:
            transcript += "\n\n" + failures
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

    def _schedule_harness_review(
        self,
        text: str,
        reply: str,
        *,
        session_id: str | None = None,
    ) -> None:
        """Review every ``harness_turn_interval`` turns, at most once per cooldown.

        Gate ordering is the cost control: the turn counter and the cooldown are
        both settled from local state BEFORE the evidence gate — which is a
        model call — is spent.
        """
        if not self.cfg.get("harness_enabled", True):
            return
        interval = int(self.cfg.get("harness_turn_interval", 12) or 0)
        if interval <= 0:
            return
        cooldown = float(self.cfg.get("harness_cooldown_min", 15) or 0) * 60
        transcript = f"USER:\n{text}\n\nASSISTANT:\n{reply}"
        review_session = str(
            session_id
            if session_id is not None
            else self.cfg["session_id"]
        )
        with self._harness_lock:
            transcripts = self._harness_transcripts.setdefault(
                review_session,
                [],
            )
            transcripts.append(transcript)
            del transcripts[:-interval]
            turns = self._harness_turns.get(review_session, 0) + 1
            self._harness_turns[review_session] = turns
            if turns < interval:
                return
            last_review = self._harness_last.get(review_session, 0.0)
            if (last_review
                    and time.monotonic() - last_review < cooldown):
                return
            if self._harness_thread and self._harness_thread.is_alive():
                return
            self._harness_turns[review_session] = 0
            self._harness_last[review_session] = time.monotonic()
            review_transcript = "\n\n".join(transcripts)
            transcripts.clear()
            review_ctx = copy.copy(self.ctx)
            review_ctx.cfg = {
                **self.cfg,
                "session_id": review_session,
            }
            review_ctx.client = copy.copy(self.ctx.client)
            provider = self.cfg.get("provider")
            review_model = self.cfg.get("model")

            def review() -> None:
                from . import harness_review
                try:
                    summary = harness_review.review(
                        review_ctx, review_transcript, reason="turn-interval")
                except Exception as exc:
                    summary = f"harness-review failed: {exc}"
                store.save_run("harness-review", summary, details={
                    "provider": provider,
                    "model": review_model,
                }, usage=store.estimate_usage(review_transcript, summary))

            try:
                self._harness_thread = threading.Thread(
                    target=review, name="birkin-harness-review", daemon=True)
                self._harness_thread.start()
            except (OSError, RuntimeError):
                self._harness_thread = None
                self._harness_turns[review_session] = interval - 1

    def new_conversation(self) -> None:
        self.agent.reset()
        self._skill_review_turns = 0
        self._memory_review_transcripts.clear()
        self._harness_turns.clear()
        self._harness_transcripts.clear()
        self._harness_last.clear()
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
        client = build_client(self.cfg, api_key)
        ctx = replace(self.ctx, client=client)
        registry = build_registry(ctx)
        self.client = client
        self.ctx = ctx
        self.agent.client = client
        self.agent.registry = registry
        self.agent.model = self.cfg.get("model")
        with self._skill_review_lock:
            self._skill_review_turns = 0
            self._memory_review_transcripts.clear()
        # The warm CLI process baked the OLD --model at spawn; drop it so the
        # next warm ask() respawns with the new model/provider.
        self.close()


def failure_context(limit: int = 5) -> str:
    """Recent deaths, for the self-improvement pass to actually learn from.

    The pass only ever saw `USER:`/`ASSISTANT:` of a turn that SUCCEEDED, so
    every timeout and every failed agent — the material worth learning from —
    was invisible to it.
    """
    from .moirai import journal
    calls = journal.recent_failed_calls(limit)
    incidents = journal.recent_incidents(limit)
    if not calls and not incidents:
        return ""
    lines = ["FAILURES (recent, from the moirai journal):"]
    for call in calls:
        lines.append(
            f"- moirai call {call.get('run_id')}#{call.get('seq')} "
            f"[{call.get('role') or '?'}/{call.get('label') or '?'}] "
            f"{(call.get('error') or '')[:300]}")
    for row in incidents:
        lines.append(
            f"- gateway {row.get('kind')} on "
            f"{row.get('channel')}:{row.get('chat_id')} after "
            f"{float(row.get('elapsed_seconds') or 0):.1f}s — "
            f"{row.get('event_count')} event(s), last "
            f"{row.get('last_event_kind') or '?'}, "
            f"partial {row.get('partial_chars')} chars")
    return "\n".join(lines)


def _build_profile_review_service(
    cfg: dict[str, Any],
) -> ProfileReviewService | None:
    profile = cfg.get("profile")
    if not (_profiles_enabled(cfg) and isinstance(profile, dict)):
        return None
    review = profile.get("background_review", {})
    if not isinstance(review, dict):
        return None
    provider = review.get("provider")
    model = review.get("model")
    if not provider or not model:
        return None
    aux_cfg = {**cfg, "provider": provider, "model": model}
    aux_key = config.get_api_key(aux_cfg) or ""
    aux_client = build_client(aux_cfg, aux_key)

    def complete(prompt: str) -> str:
        message = aux_client.complete(
            system="You review completed turns for durable role-profile updates.",
            messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}],
            tools=[],
            model=str(model),
        )
        blocks = message.get("content", []) if isinstance(message, dict) else []
        return "".join(
            str(block.get("text", ""))
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        )

    actions = ProfileActions(
        ProfileStore(config.birkin_home(), profile.get("limits", {})),
        approval_required=bool(profile.get("write_approval", False)),
    )
    return build_profile_review(cfg, actions, complete)


def build_session(cfg: Optional[dict[str, Any]] = None,
                  on_event: Optional[Callable[[str, dict[str, Any]], None]] = None
                  ) -> Session:
    cfg = dict(cfg or config.load_config())
    cfg.setdefault("session_id", uuid.uuid4().hex)
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
    checkpoint_session = [str(cfg["session_id"])]

    from . import checkpoint_state

    checkpoint_mgr = checkpoints.CheckpointManager(
        enabled=bool(cfg.get("checkpoints", True)),
        keep=int(cfg.get("checkpoint_keep", 20)),
        state_snapshot=lambda: checkpoint_state.snapshot(
            checkpoint_session[0]
        ),
        state_restore=lambda state: checkpoint_state.restore(
            checkpoint_session[0],
            state,
        ))
    hook_bus = hooks.build_bus(cfg)
    ctx = ToolContext(
        cfg=cfg, client=client, cwd=Path.cwd(),
        skills=skills, memory=memory,
        max_depth=int(cfg.get("max_depth", 2)), emit=on_event,
        tree_budget=budget.TreeBudget(cfg),
        checkpoints=checkpoint_mgr, hooks=hook_bus)
    registry = build_registry(ctx)
    profile_review_service = _build_profile_review_service(cfg)
    system = promptgate.compose_main(
        cfg, skills_index=skills.index(), memory_block=memory.render(),
        profile_block=_profile_block(cfg), harness_block=_harness_block(cfg))
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
    return Session(
        cfg=cfg,
        client=client,
        skills=skills,
        memory=memory,
        ctx=ctx,
        agent=agent,
        _checkpoint_session=checkpoint_session,
        profile_review_service=profile_review_service,
    )


def build_dry_run_packet(text: str, cfg: Optional[dict[str, Any]] = None
                         ) -> dict[str, Any]:
    """Assemble the exact prompt packet for `text` WITHOUT any model call or API
    key — the system prompt, tool names (or routed skills for CLI providers),
    and a usage estimate. Powers `birkin chat --dry-run`."""
    cfg = cfg or config.load_config()
    provider = cfg.get("provider", "anthropic")
    skills = build_manager(cfg)
    memory = Memory(cfg)

    routed = assemble_routed_skills(skills, text)
    if provider in config.CLI_PROVIDERS:
        system = promptgate.compose_cli(
            cfg, memory_block=memory.render(), profile_block=_profile_block(cfg),
            preloaded=list(routed.rendered) or None,
            harness_block=_harness_block(cfg))
        tool_names: list[str] = []
    else:
        client = LLMClient(provider="local-cli", model="", api_key="", base_url="")
        ctx = ToolContext(cfg=cfg, client=client, cwd=Path.cwd(), skills=skills,
                          memory=memory, max_depth=int(cfg.get("max_depth", 2)))
        system = promptgate.compose_main(
            cfg, skills_index=skills.index(), memory_block=memory.render(),
            profile_block=_profile_block(cfg), harness_block=_harness_block(cfg))
        if routed.rendered:
            system += (
                "\n\n## Birkin routed skills for this turn\n\n"
                + "\n\n".join(routed.rendered)
            )
        tool_names = [t["name"] for t in build_registry(ctx).specs()]

    return {
        "provider": provider,
        "model": cfg.get("model"),
        "system": system,
        "tools": tool_names,
        "routed_skills": list(routed.names),
        "user": text,
        "usage": store.estimate_usage(system, text),
    }
