"""Interactive terminal chat for birkin.

Streams the assistant's text as it arrives, shows compact tool-activity lines,
and supports a handful of slash commands. Uses ``input()`` (and ``readline``
when available) — no third-party TUI library.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from typing import Any

from . import config, selfimprove, store
from .runtime import ConfigError, Session, build_session

try:  # readline gives history/editing on POSIX; absent on stock Windows
    import readline  # noqa: F401
except ImportError:
    pass

# ANSI styling (modern terminals, incl. Windows Terminal)
DIM, BOLD, CYAN, GREEN, YELLOW, RED, RESET = (
    "\033[2m", "\033[1m", "\033[36m", "\033[32m", "\033[33m", "\033[31m", "\033[0m")

HELP = """Commands:
  /help            show this help
  /skills [name]   list skills, or show one in full
  /new             start a fresh conversation
  /model [name]    show or change the model
  /learn           reflect on this session and save skills/memory
  /permission      show auto-approved action categories
  /permission add|remove <cat>   change them (e.g. /permission add cron)
  /save            save the current conversation
  /quit, /exit     leave
Anything else is sent to the agent."""


def _make_event_printer():
    def emit(event: str, payload: dict[str, Any]) -> None:
        if event == "tool_start":
            inp = json.dumps(payload.get("input", {}), ensure_ascii=False)
            if len(inp) > 80:
                inp = inp[:80] + "…"
            sys.stdout.write(f"\n{DIM}  → {payload.get('name')} {inp}{RESET}\n")
        elif event == "tool_end":
            mark = f"{RED}✗{RESET}" if payload.get("is_error") else f"{GREEN}✓{RESET}"
            sys.stdout.write(f"{DIM}  {mark} {payload.get('name')}{RESET}\n")
        elif event == "subagent.start":
            sys.stdout.write(f"\n{DIM}  ⇲ subagent: {payload.get('task','')}{RESET}\n")
        elif event == "subagent.done":
            sys.stdout.write(f"{DIM}  ⇱ subagent done{RESET}\n")
        sys.stdout.flush()
    return emit


def _stream(piece: str) -> None:
    sys.stdout.write(piece)
    sys.stdout.flush()


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
    print(f" type {YELLOW}/help{RESET} or just chat · Ctrl-C to quit.")


def _save_session(session: Session) -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = config.sessions_dir() / f"{ts}.json"
    path.write_text(json.dumps(session.agent.messages, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return str(path)


def _handle_command(session: Session, line: str) -> bool:
    """Return True to continue the loop, False to exit."""
    parts = line.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("/quit", "/exit"):
        return False
    if cmd == "/help":
        print(HELP)
    elif cmd == "/skills":
        if arg:
            sk = session.skills.get(arg)
            print(f"\n{sk.full()}\n" if sk else f"{RED}No skill {arg!r}{RESET}")
        else:
            print(session.skills.index())
    elif cmd == "/new":
        session.new_conversation()
        print(f"{DIM}Started a new conversation.{RESET}")
    elif cmd == "/model":
        if arg:
            session.cfg["model"] = arg
            session.client.model = arg
            print(f"{DIM}Model set to {arg} (this session).{RESET}")
        else:
            print(session.cfg.get("model"))
    elif cmd == "/save":
        print(f"{DIM}Saved to {_save_session(session)}{RESET}")
    elif cmd == "/learn":
        print(f"{DIM}Reflecting…{RESET}")
        transcript = selfimprove.transcript_from_messages(session.agent.messages)
        result = selfimprove.reflect_and_learn(session.ctx, transcript)
        session.skills.reload()
        print(f"{GREEN}{result}{RESET}")
    elif cmd == "/permission":
        sub = arg.split()
        auto = list(session.cfg.get("auto_approve", []))
        if len(sub) == 2 and sub[0] in ("add", "remove"):
            cat = sub[1]
            if sub[0] == "add" and cat not in auto:
                auto.append(cat)
            elif sub[0] == "remove" and cat in auto:
                auto.remove(cat)
            session.cfg["auto_approve"] = auto
            config.save_config(session.cfg)
        print(f"{DIM}Auto-approved: {', '.join(auto) or '(none)'}. "
              f"Others need `birkin review`.{RESET}")
    else:
        print(f"{RED}Unknown command {cmd}. Try /help.{RESET}")
    return True


def run(cfg: dict[str, Any] | None = None) -> int:
    try:
        session = build_session(cfg, on_event=_make_event_printer())
    except ConfigError as exc:
        print(f"{RED}{exc}{RESET}")
        return 1

    _banner(session)
    while True:
        try:
            line = input(f"\n{BOLD}you{RESET} > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line.startswith("/"):
            if not _handle_command(session, line):
                break
            continue

        sys.stdout.write(f"\n{CYAN}birkin{RESET} > ")
        sys.stdout.flush()
        try:
            session.ask(line, on_text=_stream)
            sys.stdout.write("\n")
            store.append_activity(f"chat: {line[:120]}")
        except KeyboardInterrupt:
            print(f"\n{DIM}(interrupted){RESET}")
        except Exception as exc:  # surface, don't crash the REPL
            print(f"\n{RED}Error: {exc}{RESET}")
    print(f"{DIM}bye.{RESET}")
    return 0
