"""Core chat, plugin, and skill command registration."""

from __future__ import annotations

import argparse
from ._types import Handlers


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser], handlers: Handlers
) -> None:
    chatp = subparsers.add_parser("chat", help="interactive chat (default)")
    chatp.add_argument(
        "--dry-run",
        action="store_true",
        help="build & print the prompt packet without calling the model",
    )
    chatp.add_argument("-m", "--message", help="message to inspect with --dry-run")
    chatp.add_argument(
        "positional_message",
        nargs="?",
        help="message to inspect with --dry-run",
    )
    chatp.set_defaults(func=handlers["_cmd_chat"])

    pp = subparsers.add_parser(
        "plugins", help="inspect and install signed plugin bundles"
    )
    pps = pp.add_subparsers(dest="action", required=True)
    inspectp = pps.add_parser("inspect", help="show permissions before installation")
    inspectp.add_argument("source")
    installp = pps.add_parser("install", help="install an exact bundle version")
    installp.add_argument("source")
    installp.add_argument("--version", required=True, help="exact semantic version")
    installp.add_argument("--scope", choices=("project", "team"), default="project")
    installp.add_argument(
        "--yes", action="store_true", help="confirm disclosed permissions"
    )
    installp.add_argument(
        "--upgrade", action="store_true", help="replace an existing scope pin"
    )
    resolvep = pps.add_parser("resolve", help="show the effective project/team pin")
    resolvep.add_argument("name")
    resolvep.add_argument("--version", help="require this exact installed version")
    effectsp = pps.add_parser("effects", help="manage plugin tool effect attestations")
    effectsp.add_argument(
        "--json", dest="effect_json", action="store_true", help=argparse.SUPPRESS
    )
    effectsp.add_argument("effect_args", nargs=argparse.REMAINDER)
    effectsp.set_defaults(func=handlers["_cmd_plugin_effects"])
    for plugin_parser in (inspectp, installp, resolvep):
        plugin_parser.add_argument(
            "--json", action="store_true", help="machine-readable JSON"
        )
        plugin_parser.add_argument(
            "--key",
            action="append",
            default=[],
            metavar="KEY_ID=HEX",
            help="trusted HMAC key (repeatable)",
        )
        plugin_parser.set_defaults(func=handlers["_cmd_plugins"])

    sp = subparsers.add_parser(
        "skills", help="list skills, show one, `skills sync`, or `skills validate`"
    )
    sp.add_argument(
        "name", nargs="?", help="skill name to show, or 'sync' / 'validate'"
    )
    sp.add_argument("--from", dest="source", help="source skills dir for `skills sync`")
    sp.add_argument("--limit", type=int, default=None, help="max skills to sync")
    sp.add_argument("--force", action="store_true", help="overwrite existing mirrors")
    sp.add_argument(
        "--verbose",
        action="store_true",
        help="show warnings-only skills in `skills validate`",
    )
    sp.add_argument("target", nargs="?", help="argument for install/uninstall/scan")
    sp.add_argument("--source", help="trust source for `skills scan`")
    sp.set_defaults(func=handlers["_cmd_skills"])
