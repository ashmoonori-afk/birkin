"""Interactive terminal chat for birkin.

Streams the assistant's text, shows compact tool-activity lines, and delegates
slash commands to :mod:`birkin.slashcommands`. Uses ``input()`` (and
``readline`` when available) — no third-party TUI library.
"""

from __future__ import annotations

import sys
from typing import Any

from . import slashcommands, store, ui
from .runtime import ConfigError, Session, build_session
from .ui import CYAN, DIM, RED, RESET, YELLOW

try:  # readline gives history/editing on POSIX; absent on stock Windows
    import readline  # noqa: F401
except ImportError:
    pass

_ASCII = r"""
 ██████╗ ██╗██████╗ ██╗  ██╗██╗███╗   ██╗
 ██╔══██╗██║██╔══██╗██║ ██╔╝██║████╗  ██║
 ██████╔╝██║██████╔╝█████╔╝ ██║██╔██╗ ██║
 ██╔══██╗██║██╔══██╗██╔═██╗ ██║██║╚██╗██║
 ██████╔╝██║██║  ██║██║  ██╗██║██║ ╚████║
 ╚═════╝ ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝"""


def _banner(session: Session) -> None:
    cfg = session.cfg
    n = len(session.skills.skills)
    print(f"{CYAN}{_ASCII}{RESET}")
    print(f" {DIM}The AI agent that actually remembers you.{RESET}\n")
    print(f" model {CYAN}{cfg.get('model')}{RESET} · {n} skill(s) · "
          f"vault {DIM}{session.memory.vault}{RESET}")
    print(f" type {YELLOW}/help{RESET} for commands, or just chat · Ctrl-C to quit.")


def run(cfg: dict[str, Any] | None = None) -> int:
    try:
        session = build_session(cfg, on_event=ui.make_event_printer())
    except ConfigError as exc:
        print(f"{RED}{exc}{RESET}")
        return 1

    _banner(session)
    while True:
        try:
            line = input(f"\n{ui.BOLD}you{RESET} > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line.startswith("/"):
            if slashcommands.dispatch(session, line) == "exit":
                break
            continue

        sys.stdout.write(f"\n{CYAN}birkin{RESET} > ")
        sys.stdout.flush()
        try:
            session.ask(line, on_text=ui.stream_text)
            sys.stdout.write("\n")
            store.append_activity(f"chat: {line[:120]}")
        except KeyboardInterrupt:
            print(f"\n{DIM}(interrupted){RESET}")
        except Exception as exc:  # surface, don't crash the REPL
            print(f"\n{RED}Error: {exc}{RESET}")
    print(f"{DIM}bye.{RESET}")
    return 0
