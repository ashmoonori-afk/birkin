"""Which workers a natural-language turn may ask for, and how they are run.

Before this, a worker could only be started from the CLI. The one
natural-language surface (:mod:`birkin.moirai.trigger`) proposes a *moirai
workflow* and nothing else, so eight implemented workers were unreachable from
the surface users actually talk to: "run the self-improvement pass" in chat hit
nothing.

This module is only the contract — which workers exist, what asking for one
gets you, and what command it maps to. The natural-language door itself is the
``worker_invoke`` tool (:mod:`birkin.tools.worker_tool`), which proposes and
lets a human approve, exactly like ``companion_propose``. Python never
classifies intent with keywords here; the model names the worker, Python only
checks that the name is real.

Only workers with a real command surface are offered. ``osiris`` is declared in
:data:`birkin.worker_hooks.WORKERS` but has no implementation, so it is never
invokable, and neither is any other reserved name.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from typing import Any

from . import worker_hooks

_MAX_TASK = 4000

# worker -> (cli subcommand, what asking for it actually gets you). The
# subcommand is what the approval card shows and what runs on approval, so a
# worker without one is deliberately absent rather than silently unreachable.
WORKER_COMMANDS: dict[str, tuple[str, str]] = {
    "moirai": ("moirai",
               "deterministic multi-agent workflows across claude / codex / API"),
    "morpheus": ("morpheus", "run the self-improvement routine now"),
    "harness": ("harness",
                "the self-improvement ledger: show / history / rollback / export"),
    "odyssey": ("odyssey",
                "seed a goal-completion cycle (plan -> critique -> execute -> verify)"),
    "neurosis": ("neurosis",
                 "seed a deep-interview (Socratic clarity-gating before acting)"),
    "daedalus": ("daedalus",
                 "evidence-linked project document maps: create / refresh / show"),
}


class WorkerCallError(ValueError):
    """The named worker cannot be invoked from a natural-language turn."""


@dataclass(frozen=True)
class WorkerCall:
    """A worker the model named, before anyone runs it."""

    worker: str
    task: str

    # The approval category whose executor can actually run this. NOT
    # ``operation``: that category is a digest-bound replay of a native tool
    # call, so a worker payload sent there is rejected the moment a human
    # approves it. ``shell`` is the category that runs a command, and it is
    # already the strictest gate in the system.
    category = "shell"

    @property
    def subcommand(self) -> str:
        return WORKER_COMMANDS[self.worker][0]

    def command(self) -> str:
        """The exact command a human is approving.

        Built only from birkin's own allowlist and the running interpreter —
        the user's free text never reaches it, so there is nothing to inject.
        """
        return f'"{sys.executable}" -m birkin {self.subcommand}'

    def title(self) -> str:
        return f"run worker {self.worker}"

    def payload(self) -> dict[str, Any]:
        return {"command": self.command(), "timeout": 3600,
                "worker": self.worker, "task": self.task}


def invokable_workers() -> tuple[str, ...]:
    """Declared, implemented, non-reserved workers that have a command."""
    return tuple(
        name for name in worker_hooks.WORKERS
        if name in WORKER_COMMANDS
        and name not in worker_hooks.RESERVED_WORKERS
    )


def describe_workers() -> str:
    """One line per invokable worker, for the tool description."""
    return "; ".join(f"{name} = {WORKER_COMMANDS[name][1]}"
                     for name in invokable_workers())


def resolve(worker: Any, task: Any) -> WorkerCall:
    """Validate a model-named worker + task, or explain why it is refused.

    The model is trusted to judge which worker fits, never to be well-formed:
    an unknown name, a reserved name, and an empty or oversized task all stop
    here rather than reaching the approval queue.
    """
    if not isinstance(worker, str) or worker not in invokable_workers():
        raise WorkerCallError(
            f"unknown worker {worker!r} — invokable: "
            f"{', '.join(invokable_workers())}")
    if not isinstance(task, str):
        raise WorkerCallError("task must be text")
    cleaned = re.sub(r"\s+", " ", task).strip()
    if not cleaned:
        raise WorkerCallError("task is empty")
    if len(cleaned) > _MAX_TASK:
        raise WorkerCallError(f"task exceeds {_MAX_TASK} characters")
    return WorkerCall(worker=worker, task=cleaned)
