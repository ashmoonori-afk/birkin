"""Interactive terminal chat for birkin.

Streams the assistant's text, shows compact tool-activity lines, and delegates
slash commands to :mod:`birkin.slashcommands`. Uses ``input()`` (and
``readline`` when available) — no third-party TUI library.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from . import abortkey, inline_complete, slashcommands, store, transcripts, ui
from .runtime import ConfigError, Session, build_session
from .ui import BIRKIN_BANNER, CYAN, DIM, RED, RESET, YELLOW

try:  # readline gives history/editing on POSIX; absent on stock Windows
    import readline  # noqa: F401
except ImportError:
    pass


def _banner(session: Session) -> None:
    cfg = session.cfg
    n = len(session.skills.skills)
    print(f"{CYAN}{BIRKIN_BANNER}{RESET}")
    print(f" {DIM}The AI agent that actually remembers you.{RESET}\n")
    print(f" model {CYAN}{cfg.get('model')}{RESET} · {n} skill(s) · "
          f"vault {DIM}{session.memory.vault}{RESET}")
    print(f" type {YELLOW}/help{RESET} for commands, or just chat · "
          f"{YELLOW}Esc{RESET} (or type + Enter) interrupts a reply · Ctrl-C to quit.")
    print(f" {DIM}edit: Ctrl+←/→ word · Ctrl-W delete word · Ctrl-U/Ctrl-K clear "
          f"to start/end · ↑/↓ history{RESET}")


def run(cfg: dict[str, Any] | None = None) -> int:
    try:
        session = build_session(cfg, on_event=ui.make_event_printer())
    except ConfigError as exc:
        print(f"{RED}{exc}{RESET}")
        return 1

    _banner(session)
    # One auto-save transcript file per REPL process run (feeds nightly memory).
    run_id = f"{datetime.now():%Y%m%d-%H%M%S}-{os.getpid()}"
    hints = inline_complete.hints_from_registry(slashcommands._REGISTRY)
    history = inline_complete.load_history()
    pending = ""   # a line typed during a reply (Enter-interrupt) -> next turn
    while True:
        if pending:
            line, pending = pending, ""
            print(f"\n{ui.BOLD}you{RESET} > {line}")   # echo the carried message
        else:
            try:
                print()   # leading blank line, like the old input("\n…")
                raw = inline_complete.prompt_with_completion(
                    f"{ui.BOLD}you{RESET} > ", hints, history=history)
            except KeyboardInterrupt:
                print()
                break
            if raw is None:
                print()
                break
            line = raw.strip()
        if not line:
            continue
        inline_complete.append_history(line, prior=history)
        if line.startswith("/"):
            # A slash handler that raises (or Ctrl-C mid-command) must not
            # escape the loop — otherwise session.close() at the end is
            # skipped and the warm CLI subprocess leaks.
            try:
                if slashcommands.dispatch(session, line) == "exit":
                    break
            except KeyboardInterrupt:
                print(f"\n{DIM}(interrupted){RESET}")
            except Exception as exc:
                print(f"\n{RED}Error: {exc}{RESET}")
            continue

        # Stream the reply token-by-token so the first words appear at model
        # latency instead of after the whole turn. A spinner covers the silent
        # gaps — before the first token, and between tool calls while the model
        # 'thinks' about its next step — and is cleared by the next token or
        # tool event. (Raw text: Markdown is not re-rendered mid-stream.)
        sp: dict[str, Any] = {"cur": None}
        first = {"v": True}
        base_event = session.agent.on_event

        def stop_spin() -> None:
            if sp["cur"] is not None:
                sp["cur"].stop()
                sp["cur"] = None

        def start_spin() -> None:
            if sp["cur"] is None:
                sp["cur"] = ui.Spinner()
                sp["cur"].start()

        def on_text(piece: str) -> None:
            stop_spin()
            if first["v"]:
                first["v"] = False
                print(f"\n{CYAN}birkin{RESET} >\n", end="", flush=True)
            ui.stream_text(piece)

        def turn_event(ev: str, payload: dict) -> None:
            stop_spin()
            if base_event:
                base_event(ev, payload)
            # After a tool/subagent finishes, the model 'thinks' about the next
            # step — keep the spinner alive so that gap isn't dead air.
            if ev in ("tool_end", "subagent.done"):
                start_spin()

        session.agent.on_event = turn_event

        # Esc — or typing a new message + Enter — interrupts the in-flight turn:
        # a background listener sets session.abort (stops the LLM stream / kills
        # the CLI subprocess) and captures any typed line to send next.
        interrupted = {"v": False}

        def on_interrupt() -> None:
            if not interrupted["v"]:
                interrupted["v"] = True
                session.abort.set()
                stop_spin()
                print(f"\n{DIM}(interrupting…){RESET}")

        def on_line(text: str) -> bool:
            """A typed line during a turn: steer it instead of killing it."""
            if session.cfg.get("repl_typed_line", "steer") != "steer":
                return False
            if not session.steer(text):
                return False
            stop_spin()
            print(f"{DIM}(steering: {text.strip()[:60]}){RESET}")
            start_spin()
            return True

        listener = abortkey.listen_for_interrupt(on_interrupt, on_line)
        start_spin()
        try:
            reply = session.ask(line, on_text=on_text)  # streamed live above
            stop_spin()
            if first["v"] and (reply or "").strip():
                # Provider emitted no incremental text — print it once so the
                # reply is never silently dropped. Nothing was streamed, so
                # it's safe to Markdown-render here (no mid-stream cursor/CJK
                # hazard); the streamed path stays raw by design.
                print(f"\n{CYAN}birkin{RESET} >\n", end="")
                print(ui.render_markdown((reply or "").strip()))
            print()   # terminate the streamed line
            store.append_activity(f"chat: {line[:120]}")
            transcripts.append_turn("repl", run_id, line, reply or "",
                                    cfg=session.cfg)
        except KeyboardInterrupt:
            session.abort.set()
            stop_spin()
            print(f"\n{DIM}(interrupted){RESET}")
        except Exception as exc:  # surface, don't crash the REPL
            stop_spin()
            print(f"\n{RED}Error: {exc}{RESET}")
        finally:
            listener.stop()
            # A line typed during the reply (Enter-interrupt) becomes next input.
            pending = (getattr(listener, "pending_line", "") or "").strip()
            session.agent.on_event = base_event
    session.close()   # release the warm CLI process, if repl_warm_session
    print(f"{DIM}bye.{RESET}")
    return 0
