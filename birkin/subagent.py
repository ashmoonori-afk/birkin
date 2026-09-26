"""Run an isolated subagent for a focused sub-task.

A subagent gets a fresh conversation, a scoped toolset, and (optionally)
preloaded skills. It shares the parent's skill catalog and LLM client but does
NOT inherit the parent's message history or write to memory — keeping it
isolated and side-effect-light. Results are returned to the caller as text.
"""

from __future__ import annotations

import contextlib
import copy
import json
import threading
import time
from dataclasses import replace
from typing import Any, Optional

from . import agentruns, promptgate, store
from .agent import Agent
from .tools import ToolContext, build_registry


_HEARTBEAT_SECONDS = 30.0
_BLOCKED_POLL_SECONDS = 1.0
# An image block's base64 payload says nothing about its token cost; count a
# fixed allowance instead so a screenshot does not dominate the estimate.
_IMAGE_CHARS = 6400


def _block_chars(block: Any) -> int:
    if isinstance(block, str):
        return len(block)
    if not isinstance(block, dict):
        return 0
    kind = block.get("type")
    if kind == "text":
        return len(str(block.get("text") or ""))
    if kind == "image":
        return _IMAGE_CHARS
    if kind == "tool_use":
        return len(str(block.get("name") or "")) + len(
            json.dumps(block.get("input") or {}, ensure_ascii=False, default=str))
    if kind == "tool_result":
        content = block.get("content")
        if isinstance(content, list):
            return sum(_block_chars(item) for item in content)
        return len(str(content or ""))
    return 0


def _message_chars(messages: Any) -> int:
    total = 0
    for message in messages or []:
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            total += sum(_block_chars(block) for block in content)
        else:
            total += len(str(content or ""))
    return total


class _MeteredClient:
    """Count what a child actually sends and receives, call by call.

    Every model call re-sends the system prompt and the whole transcript, so
    the child's cost is the sum over calls, not ``len(task + result)``.
    Attribute access falls through so provider flags (``birkin_mcp`` …) keep
    working for CLI-backed clients.
    """

    def __init__(self, client: Any):
        self._client = client
        self._lock = threading.Lock()
        self.chars = 0

    def complete(self, **kwargs: Any) -> dict[str, Any]:
        sent = len(str(kwargs.get("system") or "")) + _message_chars(
            kwargs.get("messages"))
        reply = self._client.complete(**kwargs)
        received = _message_chars([reply]) if isinstance(reply, dict) else 0
        with self._lock:
            self.chars += sent + received
        return reply

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    @property
    def est_tokens(self) -> int:
        return (self.chars + 3) // 4


def _safe_emit(emit: Any, event: str, payload: dict[str, Any]) -> None:
    """Forward one event to the parent's view; a failing view never breaks
    the run (the same rule as ``Agent._emit``). A sink that refuses events
    outside its own command used to strand the record and its lease."""
    if emit:
        with contextlib.suppress(Exception):
            emit(event, payload)


class _ChildAbort:
    """The child's stop signal: its own deadline, plus the parent's Esc for an
    attached run. A detached run outlives the turn that started it, so a later
    Esc in the parent must not reach it."""

    def __init__(self, parent: Any, *, attached: bool):
        self.own = threading.Event()
        self._parent = parent if attached else None

    def is_set(self) -> bool:
        return self.own.is_set() or (
            self._parent is not None and self._parent.is_set())

    def set(self) -> None:
        self.own.set()


def run_subagent(task: str, parent_ctx: ToolContext, *,
                 skill_names: Optional[list[str]] = None,
                 max_turns: int = 12, detach: bool = False,
                 reserve_tokens: int = 0, reserve_usd: float = 0.0,
                 specialist: Any = None) -> str:
    """Run ``task`` in an isolated child agent.

    ``specialist`` is an optional :class:`birkin.summon.AgentSpec`: the child
    then carries that specialist's role, model, and tool-group scope. The
    scope is passed to ``build_registry`` as ``include``, so it narrows the
    policy the registry already enforces and can never widen it.
    """
    cfg = parent_ctx.cfg
    lease = (
        parent_ctx.tree_budget.reserve(
            tokens=reserve_tokens,
            usd=reserve_usd,
        )
        if parent_ctx.tree_budget is not None
        else None
    )
    sub_model = getattr(specialist, "model", "") or cfg.get("subagent_model")
    if not sub_model or sub_model == "default":
        # "default" means "no subagent override", not a model id: sending it
        # raw fails on OpenAI-compatible providers and silently swaps an
        # Anthropic parent's model for the alias target.
        sub_model = cfg.get("model")
    child_cfg = {**cfg, "model": sub_model}
    abort = _ChildAbort(parent_ctx.abort, attached=not detach)
    base = parent_ctx.client
    if isinstance(base, _MeteredClient):
        base = base._client  # each level meters (and bills) only its own calls
    if specialist is not None and getattr(base, "transport", "") == "cli":
        # A CLI backend runs its own tools and never sees Birkin's registry,
        # so a specialist's tool-group scope cannot be applied there. Run it
        # read-only instead (codex: read-only sandbox; claude: no tools) and
        # without Birkin's MCP tools, so it can analyze but not change state.
        base = copy.copy(base)
        base.cli_access = "read-only"
        base.birkin_mcp = False
        base.egress_enforced = False  # read-only already removes every tool
    client = _MeteredClient(base)

    # Child context: deeper, isolated from parent memory. A detached child runs
    # on its own thread, so it must not print through the parent's live UI or
    # prompt on the parent's stdin; a flagged command is queued for approval.
    # It also works on a copy of the session's command grants, so a grant it
    # gains later never leaks back into the interactive session.
    child_ctx = replace(
        parent_ctx,
        cfg=child_cfg,
        client=client,
        depth=parent_ctx.depth + 1,
        memory=None,
        abort=abort,
        emit=None if detach else parent_ctx.emit,
        shell_prompt_cb=None if detach else parent_ctx.shell_prompt_cb,
        shellguard_approved=(
            set(parent_ctx.shellguard_approved)
            if detach else parent_ctx.shellguard_approved
        ),
    )

    # Everything after the reservation must release the lease on failure;
    # a skill body that fails to read used to leak a concurrency slot.
    try:
        # Preload any requested skills' bodies directly into the prompt.
        preloaded: list[tuple[str, str]] = []
        skills = parent_ctx.skills
        if skills and skill_names:
            for nm in skill_names:
                sk = skills.get(nm)
                if sk:
                    preloaded.append((sk.name, sk.body()))

        tool_groups = (
            set(specialist.tools) if specialist is not None else None
        )
        # A specialist without the skills group cannot call load_skill, so an
        # index would only advertise a tool it does not have.
        skills_index = (
            skills.index()
            if skills and (tool_groups is None or "skills" in tool_groups)
            else ""
        )
        registry = (
            build_registry(child_ctx)
            if tool_groups is None
            else build_registry(child_ctx, include=tool_groups)
        )
        system = promptgate.compose_subagent(
            child_cfg,
            skills_index=skills_index,
            preloaded=preloaded or None,
            role_block=(
                specialist.system_block() if specialist is not None else ""
            ),
            available_tools=set(registry.names()),
        )
        specialist_name = specialist.name if specialist is not None else None
        specialist_title = getattr(specialist, "title", None) or None
        run = agentruns.register_run(task, agent=specialist_name,
                                     title=specialist_title)
    except Exception:
        if lease is not None:
            lease.release()
        raise
    run_id = run["id"]
    # A detached run outlives the tool call that started it, so its trace belongs
    # on the durable record (/attach), not interleaved into the parent's output.
    emit = None if detach else parent_ctx.emit

    def deliver_messages() -> None:
        for message in agentruns.drain_messages(run_id):
            agent.steer(message)

    def wait_while_blocked() -> None:
        # The console's abort pauses the run at the next worker boundary and
        # its resume releases it (agentruns.control); Esc or the tree deadline
        # still end the wait.
        while not abort.is_set():
            rec = agentruns.get_run(run_id)
            if rec is None or rec.get("control_state") != "blocked":
                return
            agentruns.heartbeat(run_id)
            time.sleep(_BLOCKED_POLL_SECONDS)

    def on_event(event: str, payload: dict[str, Any]) -> None:
        # The progress trail is what /attach follows, so it is written for every
        # run — a heartbeat alone tells a watcher nothing about the work.
        agentruns.progress(run_id, f"{event} {payload.get('name') or ''}")
        wait_while_blocked()
        deliver_messages()
        _safe_emit(emit, "subagent." + event, payload)

    # From here until execute() owns the run, a failure must still finish the
    # record and release the lease, or the run reads "running" until it goes
    # stale and the slot counts against every later delegation.
    try:
        # No self-improvement nudges: a child has no memory and only
        # load_skill, so "call create_skill / remember" would point at tools
        # it lacks.
        agent = Agent(client=client, system=system, registry=registry,
                      max_turns=max_turns, model=sub_model, on_event=on_event,
                      self_improve=False)
        _safe_emit(emit, "subagent.start", {
            "task": task[:200], "id": run_id, "agent": specialist_name,
            "agent_title": specialist_title,
        })
    except BaseException as exc:
        agentruns.finish_run(run_id, "error", f"{type(exc).__name__}: {exc}")
        if lease is not None:
            lease.release()
        raise

    def execute() -> str:
        result = ""
        failed = False
        done = threading.Event()
        timer: threading.Timer | None = None
        if parent_ctx.tree_budget is not None:
            deadline = parent_ctx.tree_budget.deadline
            if deadline is not None:
                timer = threading.Timer(
                    max(0.0, deadline - time.monotonic()),
                    abort.set,
                )
                timer.daemon = True
                timer.start()

        def beat() -> None:
            # A single model call or tool can outlast STALE_AFTER_SECONDS; the
            # event trail alone would then report a healthy run as stale.
            while not done.wait(_HEARTBEAT_SECONDS):
                agentruns.heartbeat(run_id)

        threading.Thread(target=beat, name=f"birkin-subagent-hb-{run_id}",
                         daemon=True).start()
        try:
            # Pick up messages queued in the short window between registration
            # and the first model call. Later messages are drained by the event
            # hook, between the agent's tool-calling turns.
            deliver_messages()
            with agentruns._run_scope(run_id):
                raw_result = agent.run(task, abort=abort)
            if (
                parent_ctx.tree_budget is not None
                and parent_ctx.tree_budget.expired()
            ):
                raise RuntimeError("subagent tree deadline exceeded")
            result = raw_result or "(subagent returned no text)"
            agentruns.finish_run(run_id, "done", result)
        except BaseException as exc:
            # BaseException: a Ctrl-C in the REPL must not leave the durable
            # record "running" until it goes stale.
            failed = True
            agentruns.finish_run(run_id, "error", f"{type(exc).__name__}: {exc}")
            raise
        finally:
            done.set()
            if timer is not None:
                timer.cancel()
            spent = max(client.est_tokens,
                        store.estimate_usage(task, result)["estTokens"])
            if lease is not None:
                lease.settle(tokens=spent)
            # The ledger is what the daily/monthly budget gate reads; without
            # this record every subagent's spend was invisible to it.
            try:
                store.save_run(
                    "subagent",
                    f"{specialist_name or 'subagent'}: {task[:120]}",
                    details={"run_id": run_id, "agent": specialist_name,
                             "model": sub_model, "detached": detach},
                    usage={"chars": client.chars, "estTokens": spent},
                )
            except OSError:
                pass  # accounting must not mask the run's own outcome
            if failed:
                # A live view that saw subagent.start must also see the run
                # end; a failing view must not replace the run's own error.
                _safe_emit(emit, "subagent.done", {
                    "chars": 0, "id": run_id, "agent": specialist_name,
                    "agent_title": specialist_title, "is_error": True,
                })
        _safe_emit(emit, "subagent.done", {
            "chars": len(result), "id": run_id, "agent": specialist_name,
            "agent_title": specialist_title,
        })
        return result

    if not detach:
        return execute()

    def background() -> None:
        try:
            execute()
        except Exception:
            # finish_run already recorded the failure on the durable record, so
            # /agents and /attach show it; re-raising here would only dump a
            # traceback into whatever unrelated turn is on screen.
            return

    threading.Thread(target=background, name=f"birkin-subagent-{run_id}",
                     daemon=True).start()
    # The REPL announces it once it finishes, whoever started it.
    agentruns.note_detached(run_id)
    return (f"Detached subagent {run_id} started. Follow it with "
            f"/attach {run_id[:8]} and steer it with /send {run_id[:8]} <text>.")
