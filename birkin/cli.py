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
    if getattr(args, "dry_run", False):
        return _dry_run(args)
    if not config.config_path().exists():  # first run -> onboard
        from .onboarding import run as onboard
        onboard()
        print()
    from .repl import run
    return run()


def _dry_run(args: argparse.Namespace) -> int:
    """Build and print the prompt packet for a message — no model call, no key."""
    from .runtime import build_dry_run_packet
    from .ui import BOLD, CYAN, DIM, RESET
    msg = args.message
    if not msg:
        try:
            msg = input("Message to inspect: ").strip()
        except (EOFError, KeyboardInterrupt):
            return 0
    if not msg:
        return 0
    packet = build_dry_run_packet(msg)
    print(f"{BOLD}=== dry run (no model called) ==={RESET}")
    print(f"provider: {CYAN}{packet['provider']}{RESET}  model: {packet['model']}")
    print(f"\n{BOLD}--- system prompt ---{RESET}\n{packet['system']}")
    if packet["tools"]:
        print(f"\n{BOLD}--- tools ---{RESET}\n{', '.join(packet['tools'])}")
    if packet["routed_skills"]:
        print(f"\n{BOLD}--- routed skills ---{RESET}\n{', '.join(packet['routed_skills'])}")
    print(f"\n{BOLD}--- user ---{RESET}\n{packet['user']}")
    u = packet["usage"]
    print(f"\n{DIM}estimate: {u['chars']} chars, ~{u['estTokens']} tokens. "
          f"No request was sent.{RESET}")
    return 0


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

    from . import menu
    from . import models as models_mod
    print(f"Current model: {cfg.get('model')}  (provider: {provider})")
    print("(discovering API + local models…)")
    found = models_mod.discover(cfg)
    labels = [f"{m.id}  [{m.source}]" + (f" · {m.note}" if m.note else "")
              for m in found]
    cur = cfg.get("model")
    default_i = next((i for i, m in enumerate(found) if m.model_value() == cur), 0)
    mi = menu.select("Choose a model", labels, default=default_i)
    if mi is None:
        return 0
    models_mod.apply_selection(cfg, found[mi])
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


# Tools grouped by "toolset" for the Available Tools panel.
_TOOL_GROUPS = ["files", "shell", "web", "skills", "memory", "subagent"]

_BIRKIN_ART = [
    " ██████╗ ██╗██████╗ ██╗  ██╗██╗███╗   ██╗",
    " ██╔══██╗██║██╔══██╗██║ ██╔╝██║████╗  ██║",
    " ██████╔╝██║██████╔╝█████╔╝ ██║██╔██╗ ██║",
    " ██╔══██╗██║██╔══██╗██╔═██╗ ██║██║╚██╗██║",
    " ██████╔╝██║██║  ██║██║  ██╗██║██║ ╚████║",
    " ╚═════╝ ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝",
]


def _cmd_tools(args: argparse.Namespace) -> int:
    """Show the Available Tools panel and enable/disable tools (like hermes)."""
    from pathlib import Path
    from . import config
    from .memory import VaultMemory
    from .skills import build_manager
    from .tools import ToolContext, build_registry
    from .ui import CYAN, DIM, GREEN, RED, RESET

    cfg = config.load_config()
    disabled = set(cfg.get("disabled_tools", []))
    if args.enable:
        disabled.discard(args.enable)
    if args.disable:
        disabled.add(args.disable)
    if args.enable or args.disable:
        cfg["disabled_tools"] = sorted(disabled)
        config.save_config(cfg)

    base = dict(cfg); base["disabled_tools"] = []
    skills, memory = build_manager(cfg), VaultMemory(cfg)
    ctx = ToolContext(cfg=base, client=None, cwd=Path.cwd(),
                      skills=skills, memory=memory)

    # group -> [tool names], skipping empty groups
    rows: list[str] = []
    total = enabled = 0
    for group in _TOOL_GROUPS:
        names = build_registry(ctx, include={group}).names()
        if not names:
            continue
        marks = []
        for n in names:
            total += 1
            if n in disabled:
                marks.append(f"{RED}{n}{RESET}")
            else:
                enabled += 1
                marks.append(n)
        rows.append(f"{CYAN}{group}{RESET}: " + ", ".join(marks))

    # Render: ASCII art on the left, toolset rows on the right (hermes-style).
    title = f"  {RESET}Available Tools{RESET}  {DIM}({enabled}/{total} enabled){RESET}"
    print(title)
    art = list(_BIRKIN_ART)
    height = max(len(art), len(rows))
    for i in range(height):
        left = f"{CYAN}{art[i]}{RESET}" if i < len(art) else " " * 42
        right = rows[i] if i < len(rows) else ""
        print(f"  {left}   {right}")
    print(f"\n{DIM}Toggle:{RESET} birkin tools --disable <name> / --enable <name>"
          f"  ·  {RED}red{RESET} = disabled")
    return 0


_CLI_ACCESS_LEVELS = [
    ("workspace", "Writable & sandboxed to the workspace (recommended)"),
    ("full", "DANGEROUS: bypass ALL approvals + sandbox "
             "(codex --dangerously-bypass-approvals-and-sandbox, "
             "claude --dangerously-skip-permissions)"),
]


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

    # CLI-agent access level (Claude Code / Codex)
    if args.access in ("workspace", "full"):
        cfg["cli_access"] = args.access
        config.save_config(cfg)
    elif args.access is None and not (args.add or args.remove):
        # Interactive picker when run with no arguments.
        from . import menu
        cur = cfg.get("cli_access", "workspace")
        labels = [f"{name} — {desc}" for name, desc in _CLI_ACCESS_LEVELS]
        di = 0 if cur == "workspace" else 1
        idx = menu.select("CLI-agent access level (Claude Code / Codex)",
                          labels, default=di)
        if idx is not None:
            chosen = _CLI_ACCESS_LEVELS[idx][0]
            if chosen == "full":
                print("⚠  'full' lets the CLI agent run ANY command and edit ANY "
                      "file with no prompts. Use only if you trust the workspace.")
            cfg["cli_access"] = chosen
            config.save_config(cfg)

    print("\nAuto-approved categories (applied without asking):")
    print("  " + (", ".join(cfg.get("auto_approve", [])) or "(none)")
          + "   (everything else is queued for `birkin review`)")
    print(f"CLI-agent access level: {cfg.get('cli_access', 'workspace')}"
          f"   (change: birkin permission --access workspace|full)")
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


def _cmd_runs(args: argparse.Namespace) -> int:
    from . import store
    from .ui import CYAN, DIM, RESET
    runs = store.list_runs(limit=int(args.limit))
    if not runs:
        print("No runs recorded yet.")
        return 0
    total_tokens = 0
    for r in runs:
        usage = r.get("usage") or {}
        tok = int(usage.get("estTokens", 0) or 0)
        total_tokens += tok
        tools = ", ".join((r.get("details") or {}).get("tools") or [])
        when = str(r.get("at", ""))[:19].replace("T", " ")
        print(f"{DIM}{when}{RESET}  {CYAN}{r.get('kind'):7}{RESET} ~{tok:>5} tok  "
              f"{str(r.get('summary', ''))[:70]}")
        if tools:
            print(f"             {DIM}tools: {tools}{RESET}")
    print(f"\n{DIM}{len(runs)} run(s), ~{total_tokens} est. tokens total. "
          f"Ledger: {store.config.ledger_path()}{RESET}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="birkin", description="Lightweight self-improving CLI agent workspace")
    sub = p.add_subparsers(dest="command")

    chatp = sub.add_parser("chat", help="interactive chat (default)")
    chatp.add_argument("--dry-run", action="store_true",
                       help="build & print the prompt packet without calling the model")
    chatp.add_argument("-m", "--message", help="message to inspect with --dry-run")
    chatp.set_defaults(func=_cmd_chat)

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

    pp = sub.add_parser("permission", help="view/change approvals & CLI-agent access level")
    pp.add_argument("--add", help="category to auto-approve (e.g. cron)")
    pp.add_argument("--remove", help="category to require approval for")
    pp.add_argument("--access", choices=["workspace", "full"],
                    help="CLI-agent access: workspace (safe) or full (dangerous bypass)")
    pp.set_defaults(func=_cmd_permission)

    cp = sub.add_parser("cron", help="list or remove daily cron jobs")
    cp.add_argument("--remove", help="job id to remove")
    cp.set_defaults(func=_cmd_cron)

    rp = sub.add_parser("runs", help="show recent run records + usage (audit log)")
    rp.add_argument("--limit", type=int, default=20)
    rp.set_defaults(func=_cmd_runs)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    if not getattr(args, "command", None):
        return _cmd_chat(args)
    return args.func(args)
