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
