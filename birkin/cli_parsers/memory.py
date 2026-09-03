"""Lineage, harness, and working-memory command registration."""

from __future__ import annotations

import argparse

from ._types import Handlers


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser], handlers: Handlers
) -> None:
    lp = subparsers.add_parser(
        "lineage",
        help="list, recover, prune, or export trusted compaction snapshots",
    )
    lps = lp.add_subparsers(dest="lineage_action", required=True)
    lps.add_parser("list", help="list trusted snapshots")
    recoverp = lps.add_parser("recover", help="print one snapshot's messages")
    recoverp.add_argument("snapshot_id")
    prunep = lps.add_parser("prune", help="keep only the newest snapshots")
    prunep.add_argument("--keep", type=int, required=True)
    exportp = lps.add_parser("export", help="export one trusted snapshot")
    exportp.add_argument("snapshot_id")
    exportp.add_argument("destination")
    for lineage_parser in lps.choices.values():
        lineage_parser.set_defaults(func=handlers["_cmd_lineage"])

    hp = subparsers.add_parser(
        "harness",
        help="the self-improvement ledger: show / history / rollback / export / refine",
    )
    hp.add_argument(
        "action",
        nargs="?",
        default="show",
        choices=["show", "history", "rollback", "export", "refine"],
        help="what to do (default: show)",
    )
    hp.add_argument(
        "target",
        nargs="*",
        help="refinement id (rollback), path (export), or instructions (refine)",
    )
    hp.add_argument(
        "--scope",
        choices=["local", "global"],
        default="global",
        help="which harness to read (default: global)",
    )
    hp.add_argument(
        "--session-id", default=None, help="session whose local harness to read"
    )
    hp.add_argument(
        "--global",
        dest="global_scope",
        action="store_true",
        help="force the global harness",
    )
    hp.add_argument(
        "-n",
        "--limit",
        type=int,
        default=None,
        help="history: show only the last N refinements",
    )
    hp.set_defaults(func=handlers["_cmd_harness"])

    working = subparsers.add_parser(
        "working-memory",
        help="inspect or update structured current-session task state",
    )
    working_actions = working.add_subparsers(
        dest="working_memory_action", required=True
    )
    working_update = working_actions.add_parser(
        "update", help="merge current task facts into one session"
    )
    working_show = working_actions.add_parser(
        "show", help="show one session's current task state"
    )
    working_clear = working_actions.add_parser(
        "clear", help="delete one session's current task state"
    )
    for action in (working_update, working_show, working_clear):
        action.add_argument("--session", required=True, help="stable session id")
        action.set_defaults(func=handlers["_cmd_working_memory"])
    working_update.add_argument("--goal", help="replace the current goal")
    working_update.add_argument(
        "--correction",
        dest="corrections",
        action="append",
        default=[],
        help="append a user correction (repeatable)",
    )
    working_update.add_argument(
        "--constraint",
        dest="constraints",
        action="append",
        default=[],
        help="append a constraint (repeatable)",
    )
    working_update.add_argument(
        "--decision",
        dest="decisions",
        action="append",
        default=[],
        help="append a decision (repeatable)",
    )
    working_update.add_argument(
        "--incomplete",
        action="append",
        default=[],
        help="append an incomplete item (repeatable)",
    )
    working_update.add_argument(
        "--evidence",
        action="append",
        default=[],
        help="append evidence (repeatable)",
    )
    working_update.add_argument(
        "--next-action",
        dest="next_actions",
        action="append",
        default=[],
        help="append a concrete next action (repeatable)",
    )
    working_show.add_argument(
        "--json", action="store_true", help="print the canonical JSON state"
    )
