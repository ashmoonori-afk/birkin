"""Worker command registration."""

from __future__ import annotations

import argparse

from ._types import Handlers


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    handlers: Handlers,
) -> None:
    whq = subparsers.add_parser(
        "worker-hook-qa",
        help="exercise approval-gated worker continuation without side effects",
    )
    whq.add_argument("--decision", required=True, choices=["approve", "reject"])
    whq.set_defaults(func=handlers["_cmd_worker_hook_qa"])

    summon = subparsers.add_parser(
        "summon",
        help="list, inspect, or summon named specialist agents "
        "(built-in or BIRKIN_HOME/agents/*.md)",
    )
    summon.add_argument("agent", nargs="?", help="agent name (omit to list)")
    summon.add_argument("task", nargs="*", help="task for the agent")
    summon.add_argument("--json", action="store_true",
                        help="print the roster or agent as JSON")
    summon.set_defaults(func=handlers["_cmd_summon"])
