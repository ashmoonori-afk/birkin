"""Run an isolated subagent for a focused sub-task.

A subagent gets a fresh conversation, a scoped toolset, and (optionally)
preloaded skills. It shares the parent's skill catalog and LLM client but does
NOT inherit the parent's message history or write to memory — keeping it
isolated and side-effect-light. Results are returned to the caller as text.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Optional

from . import agentruns, promptgate
from .agent import Agent
from .tools import ToolContext, build_registry


def run_subagent(task: str, parent_ctx: ToolContext, *,
                 skill_names: Optional[list[str]] = None,
                 max_turns: int = 12) -> str:
    cfg = parent_ctx.cfg
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

    registry = build_registry(child_ctx)
    run = agentruns.register_run(task)
    run_id = run["id"]

    def deliver_messages() -> None:
        for message in agentruns.drain_messages(run_id):
            agent.steer(message)

    def on_event(event: str, payload: dict[str, Any]) -> None:
        agentruns.heartbeat(run_id)
        deliver_messages()
        if parent_ctx.emit:
            parent_ctx.emit("subagent." + event, payload)

    agent = Agent(client=parent_ctx.client, system=system, registry=registry,
                  max_turns=max_turns, model=sub_model, on_event=on_event)

    if parent_ctx.emit:
        parent_ctx.emit("subagent.start", {"task": task[:200], "id": run_id})
    try:
        # Pick up messages queued in the short window between registration and
        # the first model call. Later messages are drained by the event hook,
        # between the agent's tool-calling turns.
        deliver_messages()
        with agentruns._run_scope(run_id):
            raw_result = agent.run(task)
        result = raw_result or "(subagent returned no text)"
        agentruns.finish_run(run_id, "done", result)
    except Exception as exc:
        agentruns.finish_run(run_id, "error", f"{type(exc).__name__}: {exc}")
        raise
    if parent_ctx.emit:
        parent_ctx.emit("subagent.done", {"chars": len(result), "id": run_id})
    return result
