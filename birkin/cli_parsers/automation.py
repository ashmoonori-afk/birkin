"""Automation, model, audit, and operational command registration."""

from __future__ import annotations

import argparse

from ._types import Handlers


def register_tools_models_and_scheduler(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser], handlers: Handlers
) -> None:
    tp = subparsers.add_parser("tools", help="list/enable/disable the agent's tools")
    tp.add_argument("--enable", help="tool name to enable")
    tp.add_argument("--disable", help="tool name to disable")
    tp.set_defaults(func=handlers["_cmd_tools"])

    cup = subparsers.add_parser(
        "computer-use",
        help="inspect native desktop capabilities and setup guidance",
    )
    cu_sub = cup.add_subparsers(
        dest="computer_use_action",
        required=True,
    )
    cu_doctor = cu_sub.add_parser(
        "doctor",
        help="report capabilities and permissions without prompting",
    )
    cu_doctor.add_argument("--json", action="store_true")
    cu_doctor.set_defaults(func=handlers["_cmd_computer_use"])
    cu_setup = cu_sub.add_parser(
        "setup",
        help="print explicit install and least-privilege permission steps",
    )
    cu_setup.add_argument("--json", action="store_true")
    cu_setup.set_defaults(func=handlers["_cmd_computer_use"])

    mp = subparsers.add_parser(
        "model",
        aliases=["models"],
        help="choose the model (interactive, like `hermes model`)",
    )
    mp.add_argument(
        "name", nargs="?", help="set this model directly (skips the picker)"
    )
    mp.set_defaults(func=handlers["_cmd_model"])

    # `nightly` remains an argv-level compatibility alias so argparse does not
    # leak the supposedly hidden command as ``==SUPPRESS==`` in top-level help.
    npar = subparsers.add_parser(
        "morpheus",
        help="run the self-improvement routine now (Morpheus)",
    )
    npar.add_argument(
        "--dry-run",
        action="store_true",
        help="analyze but propose nothing for execution",
    )
    npar.set_defaults(func=handlers["_cmd_morpheus"])

    dp = subparsers.add_parser("daemon", help="run the morpheus + cron scheduler")
    dp.add_argument(
        "--install",
        action="store_true",
        help="register an OS-native daily task instead of running the loop",
    )
    dp.set_defaults(func=handlers["_cmd_daemon"])

    ap = subparsers.add_parser("auth", help="sign in to a subscription backend (codex)")
    ap.add_argument(
        "provider",
        nargs="?",
        default="codex",
        help="codex (login/status/logout/import) | claude (status)",
    )
    ap.add_argument(
        "action", nargs="?", default="status", help="login | status | logout | import"
    )
    ap.set_defaults(func=handlers["_cmd_auth"])

    subparsers.add_parser(
        "review", help="approve/reject pending proposed actions"
    ).set_defaults(func=handlers["_cmd_review"])


def register_operations(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser], handlers: Handlers
) -> None:
    subparsers.add_parser(
        "update", help="pull new code from the repo (fast-forward only)"
    ).set_defaults(func=handlers["_cmd_update"])

    cmp_p = subparsers.add_parser(
        "compare", help="blind A/B: run one prompt through two models"
    )
    cmp_p.add_argument("prompt", nargs="*", help="the prompt to compare")
    cmp_p.add_argument("--a", help="model A (default: current model)")
    cmp_p.add_argument("--b", help="model B (default: a complementary tier)")
    cmp_p.set_defaults(func=handlers["_cmd_compare"])

    pp = subparsers.add_parser(
        "permission", help="view/change approvals & CLI-agent access level"
    )
    pp.add_argument("--add", help="category to auto-approve (e.g. cron)")
    pp.add_argument("--remove", help="category to require approval for")
    pp.add_argument(
        "--access",
        choices=["workspace", "full"],
        help="CLI-agent access: workspace (safe) or full (dangerous bypass)",
    )
    pp.set_defaults(func=handlers["_cmd_permission"])

    cp = subparsers.add_parser("cron", help="list or remove daily cron jobs")
    cp.add_argument("--remove", help="job id to remove")
    cp.set_defaults(func=handlers["_cmd_cron"])

    comp = subparsers.add_parser(
        "companion", help="commitments birkin follows up on (add/activate/list/answer)"
    )
    comp.add_argument(
        "action",
        choices=[
            "status",
            "list",
            "bind",
            "add",
            "activate",
            "answer",
            "policy",
            "pause",
            "resume",
            "delete",
            "events",
        ],
        help="what to do",
    )
    comp.add_argument(
        "target", nargs="?", default="", help="commitment id, or chat id for bind"
    )
    comp.add_argument("--outcome", default="", help="what the user committed to")
    comp.add_argument(
        "--next", dest="next_action", default="", help="the next concrete step"
    )
    comp.add_argument(
        "--source",
        default="",
        help="source reference, e.g. telegram:<chat>:<message-id>",
    )
    comp.add_argument("--context", default="", help="context id (telegram:<chat>)")
    comp.add_argument("--at", default="", help="check-in time (ISO 8601)")
    comp.add_argument("--tz", default="UTC", help="IANA timezone name")
    comp.add_argument(
        "--offset",
        type=int,
        default=None,
        help="UTC offset in minutes (fallback without a tz database)",
    )
    comp.add_argument(
        "--do",
        default="",
        choices=["", "done", "blocked", "snooze", "stop", "wrong"],
        help="answer: how the check-in was answered",
    )
    comp.add_argument(
        "--snooze-minutes",
        type=int,
        default=60,
        help="answer --do snooze: how long to wait",
    )
    comp.add_argument(
        "--enable", action="store_true", help="policy: turn proactive check-ins on"
    )
    comp.add_argument("--quiet-start", default="", help="policy: HH:MM")
    comp.add_argument("--quiet-end", default="", help="policy: HH:MM")
    comp.add_argument(
        "--daily-cap", type=int, default=None, help="policy: max sends per day"
    )
    comp.add_argument(
        "--cooldown", type=int, default=None, help="policy: minutes between sends"
    )
    comp.set_defaults(func=handlers["_cmd_companion"])

    rp = subparsers.add_parser(
        "runs", help="show recent run records + usage (audit log)"
    )
    rp.add_argument("--limit", type=int, default=20)
    rp.set_defaults(func=handlers["_cmd_runs"])

    subparsers.add_parser(
        "budget", help="show token budget usage vs caps"
    ).set_defaults(func=handlers["_cmd_budget"])

    subparsers.add_parser(
        "reindex",
        help="rebuild the memory-palace index (zones, terms, dynamics)",
    ).set_defaults(func=handlers["_cmd_reindex"])

    cur = subparsers.add_parser(
        "curate", help="skill lifecycle pass: report stale, archive unused user skills"
    )
    cur.add_argument("--dry-run", action="store_true", help="report only; move nothing")
    cur.set_defaults(func=handlers["_cmd_curate"])

    cm = subparsers.add_parser(
        "curate-memory",
        help="model-agnostic memory-vault curation (any provider proposes a "
        "plan; a deterministic executor applies only the safe ops)",
    )
    cm.add_argument(
        "--provider",
        default=None,
        help="claude | codex | api | gemini | local | gemini-api "
        "| nvidia | freellmapi (default: config provider)",
    )
    cm.add_argument("--model", default=None)
    cm.add_argument(
        "--dry-run",
        action="store_true",
        help="propose and gate the plan, print it, change nothing",
    )
    cm.set_defaults(func=handlers["_cmd_curate_memory"])
