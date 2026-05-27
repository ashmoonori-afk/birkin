"""birkin command-line entry point.

Subcommands:
  (none) / chat   start interactive chat
  skills [name]   list skills, or print one in full
  web             launch the local WebUI
  setup           configure provider / model / API key
  nightly         run the 4 AM self-improvement routine now
  daemon          run the scheduler that triggers nightly + cron jobs
  review          review and approve/reject pending proposed actions
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional


def _cmd_chat(args: argparse.Namespace) -> int:
    from .repl import run
    return run()


def _cmd_skills(args: argparse.Namespace) -> int:
    from . import config
    from .skills import build_manager
    mgr = build_manager(config.load_config())
    if args.name:
        sk = mgr.get(args.name)
        if not sk:
            print(f"No skill named {args.name!r}")
            return 1
        print(sk.full())
        return 0
    if not mgr.skills:
        print("No skills installed.")
        return 0
    print(mgr.index())
    return 0


def _cmd_web(args: argparse.Namespace) -> int:
    from .web import run
    return run(port=args.port, open_browser=not args.no_browser)


def _cmd_setup(args: argparse.Namespace) -> int:
    from . import config
    cfg = config.load_config()
    print("birkin setup — press Enter to keep the current value.\n")

    def ask(label: str, key: str) -> None:
        cur = cfg.get(key)
        val = input(f"{label} [{cur}]: ").strip()
        if val:
            cfg[key] = val

    ask("Provider (anthropic|openai)", "provider")
    ask("Model", "model")
    ask("Subagent model", "subagent_model")
    ask("Base URL (blank = provider default)", "base_url")
    ask("Obsidian vault path", "vault_path")
    ask("Nightly hour (0-23)", "nightly_hour")

    key = input("API key (leave blank to use the environment variable): ").strip()
    if key:
        cfg["api_key"] = key

    path = config.save_config(cfg)
    print(f"\nSaved to {path}")
    return 0


def _cmd_nightly(args: argparse.Namespace) -> int:
    from .nightly import run_once
    return run_once(dry_run=args.dry_run)


def _cmd_daemon(args: argparse.Namespace) -> int:
    from .scheduler import install_os_schedule, run_daemon
    if args.install:
        return install_os_schedule()
    return run_daemon()


def _cmd_review(args: argparse.Namespace) -> int:
    from .approvals import review_cli
    return review_cli()


def _cmd_permission(args: argparse.Namespace) -> int:
    from . import config
    cfg = config.load_config()
    auto = list(cfg.get("auto_approve", []))
    if args.add:
        if args.add not in auto:
            auto.append(args.add)
    if args.remove and args.remove in auto:
        auto.remove(args.remove)
    if args.add or args.remove:
        cfg["auto_approve"] = auto
        config.save_config(cfg)
    print("Auto-approved categories (applied without asking):")
    print("  " + (", ".join(auto) or "(none)"))
    print("Everything else is queued for `birkin review`.")
    return 0


def _cmd_cron(args: argparse.Namespace) -> int:
    from . import cron
    jobs = cron.load_jobs()
    if args.remove:
        ok = cron.remove_job(args.remove)
        print("removed." if ok else "no such job id.")
        return 0 if ok else 1
    if not jobs:
        print("No cron jobs. The nightly routine can propose some for approval.")
        return 0
    for j in jobs:
        state = "on" if j.get("enabled", True) else "off"
        print(f"{j['id']}  {int(j.get('hour',0)):02d}:{int(j.get('minute',0)):02d}  "
              f"[{state}] {j.get('type')}  {j.get('name')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="birkin", description="Lightweight self-improving CLI agent workspace")
    sub = p.add_subparsers(dest="command")

    sub.add_parser("chat", help="interactive chat (default)").set_defaults(func=_cmd_chat)

    sp = sub.add_parser("skills", help="list skills or show one")
    sp.add_argument("name", nargs="?", help="skill name to show in full")
    sp.set_defaults(func=_cmd_skills)

    wp = sub.add_parser("web", help="launch the local WebUI")
    wp.add_argument("--port", type=int, default=None)
    wp.add_argument("--no-browser", action="store_true")
    wp.set_defaults(func=_cmd_web)

    sub.add_parser("setup", help="configure provider/model/key").set_defaults(func=_cmd_setup)

    npar = sub.add_parser("nightly", help="run the self-improvement routine now")
    npar.add_argument("--dry-run", action="store_true", help="analyze but propose nothing for execution")
    npar.set_defaults(func=_cmd_nightly)

    dp = sub.add_parser("daemon", help="run the nightly/cron scheduler")
    dp.add_argument("--install", action="store_true",
                    help="register an OS-native daily task instead of running the loop")
    dp.set_defaults(func=_cmd_daemon)

    sub.add_parser("review", help="approve/reject pending proposed actions").set_defaults(func=_cmd_review)

    pp = sub.add_parser("permission", help="view/change auto-approved action categories")
    pp.add_argument("--add", help="category to auto-approve (e.g. cron)")
    pp.add_argument("--remove", help="category to require approval for")
    pp.set_defaults(func=_cmd_permission)

    cp = sub.add_parser("cron", help="list or remove daily cron jobs")
    cp.add_argument("--remove", help="job id to remove")
    cp.set_defaults(func=_cmd_cron)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    if not getattr(args, "command", None):
        return _cmd_chat(args)
    return args.func(args)
