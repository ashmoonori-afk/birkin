"""Interactive terminal chat for birkin.

Streams the assistant's text, shows compact tool-activity lines, and delegates
slash commands to :mod:`birkin.slashcommands`. Uses ``input()`` (and
``readline`` when available) — no third-party TUI library.
"""

from __future__ import annotations

import sys
from typing import Any

from . import inline_complete, slashcommands, store, ui
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
    hints = inline_complete.hints_from_registry(slashcommands._REGISTRY)
    while True:
        try:
            print()   # leading blank line, like the old input("\n…")
            raw = inline_complete.prompt_with_completion(
                f"{ui.BOLD}you{RESET} > ", hints)
        except KeyboardInterrupt:
            print()
            break
        if raw is None:
            print()
            break
        line = raw.strip()
        if not line:
            continue
        if line.startswith("/"):
            if slashcommands.dispatch(session, line) == "exit":
                break
            continue

        # Spin while the agent works (tool activity stops the spinner), then
        # render the full reply as Markdown. Buffering the reply lets us render
        # cleanly for both streaming (API) and non-streaming (CLI) backends.
        spinner = ui.Spinner()
        spinning = {"v": True}
        base_event = session.agent.on_event

        def stop_spin() -> None:
            if spinning["v"]:
                spinning["v"] = False
                spinner.stop()

        def turn_event(ev: str, payload: dict) -> None:
            stop_spin()
            if base_event:
                base_event(ev, payload)

        session.agent.on_event = turn_event
        spinner.start()
        try:
            reply = session.ask(line)  # buffered (no live token printing)
            stop_spin()
            print(f"\n{CYAN}birkin{RESET} >\n")
            print(ui.render_markdown((reply or "").strip()))
            store.append_activity(f"chat: {line[:120]}")
        except KeyboardInterrupt:
            stop_spin()
            print(f"\n{DIM}(interrupted){RESET}")
        except Exception as exc:  # surface, don't crash the REPL
            stop_spin()
            print(f"\n{RED}Error: {exc}{RESET}")
        finally:
            session.agent.on_event = base_event
    print(f"{DIM}bye.{RESET}")
    return 0
