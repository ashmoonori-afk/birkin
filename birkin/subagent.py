"""Run an isolated subagent for a focused sub-task.

A subagent gets a fresh conversation, a scoped toolset, and (optionally)
preloaded skills. It shares the parent's skill catalog and LLM client but does
NOT inherit the parent's message history or write to memory — keeping it
isolated and side-effect-light. Results are returned to the caller as text.
"""

from __future__ import annotations

import threading
import time
from dataclasses import replace
from typing import Any, Optional

from . import agentruns, promptgate, store
from .agent import Agent
from .tools import ToolContext, build_registry


def run_subagent(task: str, parent_ctx: ToolContext, *,
                 skill_names: Optional[list[str]] = None,
                 max_turns: int = 12, detach: bool = False,
                 reserve_tokens: int = 0, reserve_usd: float = 0.0) -> str:
    cfg = parent_ctx.cfg
    lease = (
        parent_ctx.tree_budget.reserve(
            tokens=reserve_tokens,
            usd=reserve_usd,
        )
        if parent_ctx.tree_budget is not None
        else None
    )
    sub_model = cfg.get("subagent_model") or cfg.get("model")
    child_cfg = {**cfg, "model": sub_model}

    # Child context: deeper, isolated from parent memory.
    child_ctx = replace(
        parent_ctx,
        cfg=child_cfg,
        depth=parent_ctx.depth + 1,
        memory=None,
    )

    # Preload any requested skills' bodies directly into the prompt.
    preloaded: list[tuple[str, str]] = []
    skills = parent_ctx.skills
    if skills and skill_names:
        for nm in skill_names:
            sk = skills.get(nm)
            if sk:
                preloaded.append((sk.name, sk.body()))

    skills_index = skills.index() if skills else ""
    system = promptgate.compose_subagent(
        child_cfg,
        skills_index=skills_index,
        preloaded=preloaded or None,
    )

    try:
        registry = build_registry(child_ctx)
        run = agentruns.register_run(task)
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

    def on_event(event: str, payload: dict[str, Any]) -> None:
        # The progress trail is what /attach follows, so it is written for every
        # run — a heartbeat alone tells a watcher nothing about the work.
        agentruns.progress(run_id, f"{event} {payload.get('name') or ''}")
        deliver_messages()
        if emit:
            emit("subagent." + event, payload)

    agent = Agent(client=parent_ctx.client, system=system, registry=registry,
                  max_turns=max_turns, model=sub_model, on_event=on_event)

    if emit:
        emit("subagent.start", {"task": task[:200], "id": run_id})

    def execute() -> str:
        result = ""
        abort = threading.Event()
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
        except Exception as exc:
            agentruns.finish_run(run_id, "error", f"{type(exc).__name__}: {exc}")
            raise
        finally:
            if timer is not None:
                timer.cancel()
            if lease is not None:
                actual = store.estimate_usage(task, result)["estTokens"]
                lease.settle(tokens=actual)
        if emit:
            emit("subagent.done", {"chars": len(result), "id": run_id})
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
    return (f"Detached subagent {run_id} started. Follow it with "
            f"/attach {run_id[:8]} and steer it with /send {run_id[:8]} <text>.")
