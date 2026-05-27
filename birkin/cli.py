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
    from . import config
    if not config.config_path().exists():  # first run -> onboard
        from .onboarding import run as onboard
        onboard()
        print()
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
    from .onboarding import run
    return run()


def _cmd_model(args: argparse.Namespace) -> int:
    """Pick the model from the CLI, hermes-style (`birkin model`)."""
    from . import config
    cfg = config.load_config()
    provider = cfg.get("provider", "anthropic")

    if args.name:  # non-interactive: set directly
        cfg["model"] = args.name
        config.save_config(cfg)
        print(f"Model set to {args.name}")
        return 0

    from . import models as models_mod
    print(f"Current model: {cfg.get('model')}  (provider: {provider})")
    print(f"{'(fetching API + local models…)'}\n")
    found = models_mod.discover(cfg)
    models_mod.render(found, cfg.get("model"))
    print("    Or type a model name directly.")
    try:
        sel = input("\nChoose [number or name, blank to keep]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return 0
    if not sel:
        return 0
    if sel.isdigit() and 1 <= int(sel) <= len(found):
        models_mod.apply_selection(cfg, found[int(sel) - 1])
    else:
        cfg["model"] = sel
    config.save_config(cfg)
    print(f"Model set to {cfg['model']} (provider: {cfg.get('provider')})")
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


def _cmd_gateway(args: argparse.Namespace) -> int:
    from .gateway import run
    return run()


def _cmd_tools(args: argparse.Namespace) -> int:
    """List the agent's tools and enable/disable them (like `hermes tools`)."""
    from pathlib import Path
    from . import config
    from .memory import VaultMemory
    from .skills import build_manager
    from .tools import ToolContext, build_registry

    cfg = config.load_config()
    disabled = set(cfg.get("disabled_tools", []))

    if args.enable:
        disabled.discard(args.enable)
    if args.disable:
        disabled.add(args.disable)
    if args.enable or args.disable:
        cfg["disabled_tools"] = sorted(disabled)
        config.save_config(cfg)

    ctx = ToolContext(cfg=cfg, client=None, cwd=Path.cwd(),
                      skills=build_manager(cfg), memory=VaultMemory(cfg))
    # Build with no disabled filter so we can show every tool's state.
    full = build_registry(ToolContext(cfg={**cfg, "disabled_tools": []},
                                      client=None, cwd=Path.cwd(),
                                      skills=ctx.skills, memory=ctx.memory))
    for spec in full.specs():
        state = "off" if spec["name"] in disabled else "on "
        print(f"  [{state}] {spec['name']} — {spec['description'][:70]}")
    print("\nToggle with: birkin tools --disable <name> / --enable <name>")
    return 0


def _cmd_permission(args: argparse.Namespace) -> int:
    from . import config
    cfg = config.load_config()
    auto = list(cfg.get("auto_approve", []))
    if args.add:
        if args.add in ("shell", "cron"):
            print("⚠  Warning: auto-approving '" + args.add + "' lets the agent "
                  "and the unattended nightly routine run it WITHOUT asking — "
                  "including arbitrary shell commands at 04:00. Only do this if "
                  "you fully trust the setup.")
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

    sub.add_parser("setup", help="guided onboarding wizard").set_defaults(func=_cmd_setup)
    sub.add_parser("onboard", help="alias for setup (first-run wizard)").set_defaults(func=_cmd_setup)

    sub.add_parser("gateway", help="run birkin as a service (HTTP / Telegram channels)").set_defaults(func=_cmd_gateway)

    tp = sub.add_parser("tools", help="list/enable/disable the agent's tools")
    tp.add_argument("--enable", help="tool name to enable")
    tp.add_argument("--disable", help="tool name to disable")
    tp.set_defaults(func=_cmd_tools)

    mp = sub.add_parser("model", help="choose the model (interactive, like `hermes model`)")
    mp.add_argument("name", nargs="?", help="set this model directly (skips the picker)")
    mp.set_defaults(func=_cmd_model)

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
