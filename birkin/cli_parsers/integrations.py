"""MCP, workflow, session, and project command registration."""

from __future__ import annotations

import argparse

from ._types import Handlers


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser], handlers: Handlers
) -> None:
    tp_ = subparsers.add_parser("trace", help="print a run record (audit replay)")
    tp_.add_argument("run_id", help="run id (or a substring) — see `birkin runs`")
    tp_.set_defaults(func=handlers["_cmd_trace"])

    mcpp = subparsers.add_parser(
        "mcp",
        help=(
            "manage external Claude MCP servers (not inherited when "
            "egress enforcement is enabled)"
        ),
    )
    mcpp.add_argument(
        "args",
        nargs=argparse.REMAINDER,
        help="passed straight to `claude mcp` (e.g. list, add, remove, get)",
    )
    mcpp.set_defaults(func=handlers["_cmd_mcp"])

    subparsers.add_parser(
        "mcp-serve",
        help="run birkin as an MCP server (stdio) exposing memory/skills/propose "
        "tools — used by Morpheus and the gateway via `claude --mcp-config`",
    ).set_defaults(func=handlers["_cmd_mcp_serve"])

    moi = subparsers.add_parser(
        "moirai", help="deterministic multi-agent workflows across claude / codex / API"
    )
    moi.add_argument(
        "action", nargs="?", default="list", help="run | list | status | resume"
    )
    moi.add_argument(
        "script",
        nargs="?",
        default="",
        help="workflow file or name (run); run id (status / resume)",
    )
    moi.add_argument(
        "--run-id", dest="run_id", default="", help="run id (status / resume)"
    )
    moi.add_argument(
        "--bind",
        action="append",
        default=[],
        metavar="ROLE=SPEC",
        help="pin a role to a model, e.g. --bind critic=claude:opus",
    )
    moi.add_argument(
        "--args",
        default="",
        metavar="JSON",
        help="JSON object passed to the script as m.args",
    )
    moi.add_argument(
        "--defaults",
        action="store_true",
        help="skip the picker; resolve bindings non-interactively",
    )
    moi.add_argument(
        "--bind-save",
        dest="bind_save",
        action="store_true",
        help="save the chosen bindings as your defaults",
    )
    moi.add_argument("--limit", type=int, default=10)
    moi.set_defaults(func=handlers["_cmd_moirai"])

    ses = subparsers.add_parser(
        "sessions", help="list saved conversations, or export one as Markdown you own"
    )
    ses.add_argument(
        "--all",
        dest="legacy_all",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    ses.add_argument(
        "--vault",
        dest="legacy_vault",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    sess = ses.add_subparsers(dest="action")
    export_session = sess.add_parser(
        "export",
        help="export saved sessions as Markdown",
    )
    export_session.add_argument(
        "name",
        nargs="*",
        help="session name(s) to export",
    )
    export_session.add_argument(
        "--all",
        action="store_true",
        help="export every saved session",
    )
    export_session.add_argument(
        "--vault",
        action="store_true",
        help="file the export in the vault's journal zone",
    )
    live_sessions = sess.add_parser(
        "live",
        help="inspect live agent sessions grouped by observed cwd",
    )
    ses.set_defaults(
        func=handlers["_cmd_sessions"],
        name=[],
        all=False,
        vault=False,
    )
    export_session.set_defaults(func=handlers["_cmd_sessions"])
    live_sessions.set_defaults(func=handlers["_cmd_live_sessions"])

    ody = subparsers.add_parser(
        "odyssey",
        help="seed a goal-completion cycle (plan -> critique -> execute -> "
        "verify); then run /odyssey in chat to drive it",
    )
    ody.add_argument("goal", nargs=argparse.REMAINDER, help="the goal")
    ody.set_defaults(func=handlers["_cmd_odyssey"])

    nrp = subparsers.add_parser(
        "neurosis",
        help="seed a deep-interview (Socratic clarity-gating before acting); "
        "then run /neurosis in chat (REPL or gateway) to drive it",
    )
    nrp.add_argument(
        "idea",
        nargs=argparse.REMAINDER,
        help="the vague idea (optionally --quick|--standard|--deep)",
    )
    nrp.set_defaults(func=handlers["_cmd_neurosis"])

    dae = subparsers.add_parser(
        "daedalus",
        help="evidence-linked project document maps: create / refresh / show / "
        "note / profile",
    )
    dae_actions = dae.add_subparsers(dest="daedalus_action", required=True)
    dae_create = dae_actions.add_parser(
        "create", help="scan a project tree and write its first revision"
    )
    dae_refresh = dae_actions.add_parser(
        "refresh", help="re-scan under a CAS token; human notes survive intact"
    )
    dae_show = dae_actions.add_parser("show", help="print the rendered document")
    dae_note = dae_actions.add_parser(
        "note", help="append a human note (refresh never rewrites it)"
    )
    dae_actions.add_parser("profile", help="print the worker profile as json")
    for dae_parser in (dae_create, dae_refresh, dae_show, dae_note):
        dae_parser.add_argument("slug", help="document slug")
    for dae_parser in (dae_create, dae_refresh):
        dae_parser.add_argument(
            "--root", default=None, help="project root to scan (default: cwd)"
        )
    dae_refresh.add_argument(
        "--expected-token", required=True, help="the token you last read, e.g. cas-2"
    )
    dae_note.add_argument("--text", required=True, help="the note text")
    dae_note.add_argument(
        "--ref",
        action="append",
        default=[],
        help="node id this note references (repeatable)",
    )
    for dae_parser in dae_actions.choices.values():
        dae_parser.set_defaults(func=handlers["_cmd_daedalus"])
