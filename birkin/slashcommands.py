"""Slash-command system for the birkin REPL.

A small registry so commands stay easy to add and self-documenting. Each
``Command`` carries a summary + usage for ``/help``. Handlers receive
``(session, arg)`` and return ``"exit"`` to leave the REPL, or anything else to
continue.

This set is intentionally broader and more detailed than hermes' built-ins.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from . import config, selfimprove, store, ui
from .ui import BOLD, CYAN, DIM, GREEN, RED, RESET, YELLOW


@dataclass
class Command:
    name: str
    summary: str
    usage: str
    handler: Callable[[Any, str], Optional[str]]
    aliases: list[str] = field(default_factory=list)


_REGISTRY: dict[str, Command] = {}
_ALIASES: dict[str, str] = {}


def command(name: str, summary: str, usage: str = "", aliases: Optional[list[str]] = None):
    def deco(fn: Callable[[Any, str], Optional[str]]) -> Callable:
        cmd = Command(name=name, summary=summary, usage=usage or f"/{name}",
                      handler=fn, aliases=aliases or [])
        _REGISTRY[name] = cmd
        for a in cmd.aliases:
            _ALIASES[a] = name
        return fn
    return deco


# -- dispatch --------------------------------------------------------------

def dispatch(session: Any, line: str) -> str:
    """Run a slash command. Returns "exit" or "continue"."""
    parts = line[1:].split(maxsplit=1)
    if not parts:
        return "continue"
    name = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    name = _ALIASES.get(name, name)
    cmd = _REGISTRY.get(name)
    if not cmd:
        print(f"{RED}Unknown command /{name}. Try /help.{RESET}")
        return "continue"
    result = cmd.handler(session, arg)
    return "exit" if result == "exit" else "continue"


# -- helpers ---------------------------------------------------------------

def _last_user_index(messages: list[dict[str, Any]]) -> int:
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if m.get("role") == "user" and any(
                b.get("type") == "text" for b in m.get("content", [])):
            return i
    return -1


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    idx = _last_user_index(messages)
    if idx < 0:
        return ""
    for b in messages[idx]["content"]:
        if b.get("type") == "text":
            return b["text"]
    return ""


# -- conversation ----------------------------------------------------------

@command("help", "List commands, or show detailed help for one.", "/help [command]")
def _help(session: Any, arg: str) -> None:
    if arg:
        cmd = _REGISTRY.get(_ALIASES.get(arg.lstrip("/"), arg.lstrip("/")))
        if not cmd:
            print(f"{RED}No such command: {arg}{RESET}")
            return
        print(f"{BOLD}/{cmd.name}{RESET} — {cmd.summary}")
        print(f"  usage: {cmd.usage}")
        if cmd.aliases:
            print(f"  aliases: {', '.join('/' + a for a in cmd.aliases)}")
        return
    print(f"{BOLD}Slash commands{RESET} (use /help <name> for detail):")
    for name in sorted(_REGISTRY):
        c = _REGISTRY[name]
        al = f" {DIM}({', '.join('/' + a for a in c.aliases)}){RESET}" if c.aliases else ""
        print(f"  {CYAN}/{name}{RESET}{al} — {c.summary}")


@command("new", "Start a fresh conversation (clears history).", "/new", aliases=["reset"])
def _new(session: Any, arg: str) -> None:
    session.new_conversation()
    print(f"{DIM}Started a new conversation.{RESET}")


@command("retry", "Re-run your last message.", "/retry")
def _retry(session: Any, arg: str) -> None:
    text = _last_user_text(session.agent.messages)
    if not text:
        print(f"{DIM}Nothing to retry.{RESET}")
        return
    idx = _last_user_index(session.agent.messages)
    session.agent.messages = session.agent.messages[:idx]
    sys_write(session, text)


@command("undo", "Remove the last exchange (your message + the reply).", "/undo")
def _undo(session: Any, arg: str) -> None:
    idx = _last_user_index(session.agent.messages)
    if idx < 0:
        print(f"{DIM}Nothing to undo.{RESET}")
        return
    session.agent.messages = session.agent.messages[:idx]
    print(f"{DIM}Removed the last exchange ({len(session.agent.messages)} messages left).{RESET}")


@command("compact", "Summarize the conversation to shrink context.", "/compact",
         aliases=["compress"])
def _compact(session: Any, arg: str) -> None:
    msgs = session.agent.messages
    if len(msgs) < 4:
        print(f"{DIM}Conversation is already short.{RESET}")
        return
    transcript = selfimprove.transcript_from_messages(msgs, limit=200)
    print(f"{DIM}Summarizing…{RESET}")
    try:
        res = session.client.complete(
            system="You compress conversations. Produce a dense summary that "
                   "preserves decisions, facts, open threads, and user "
                   "preferences. No preamble.",
            messages=[{"role": "user", "content": [{"type": "text",
                      "text": "Summarize this conversation:\n\n" + transcript}]}],
            tools=None)
        summary = "".join(b["text"] for b in res["content"] if b.get("type") == "text")
    except Exception as exc:
        print(f"{RED}Compact failed: {exc}{RESET}")
        return
    session.agent.messages = [{"role": "user", "content": [{"type": "text",
        "text": "[Summary of earlier conversation]\n" + summary}]}]
    print(f"{GREEN}Compacted to a summary ({len(summary)} chars).{RESET}")


@command("clear", "Clear the screen.", "/clear")
def _clear(session: Any, arg: str) -> None:
    import os
    os.system("cls" if os.name == "nt" else "clear")


# -- model / provider ------------------------------------------------------

@command("model", "Show or set the model.", "/model [name]")
def _model(session: Any, arg: str) -> None:
    if arg:
        session.cfg["model"] = arg
        session.client.model = arg
        config.save_config(session.cfg)
        print(f"{DIM}Model set to {arg}.{RESET}")
    else:
        print(session.cfg.get("model"))


@command("models", "List available models (API + local).", "/models")
def _models(session: Any, arg: str) -> None:
    from . import models as models_mod
    found = models_mod.discover(session.cfg)
    models_mod.render(found, session.cfg.get("model"))


@command("provider", "Show or switch provider (anthropic|openai).", "/provider [name]")
def _provider(session: Any, arg: str) -> None:
    if arg in ("anthropic", "openai"):
        session.cfg["provider"] = arg
        config.save_config(session.cfg)
        print(f"{DIM}Provider set to {arg}. Restart chat to apply.{RESET}")
    else:
        print(session.cfg.get("provider"))


@command("temp", "Show or set sampling temperature.", "/temp [0.0-1.0]")
def _temp(session: Any, arg: str) -> None:
    if arg:
        try:
            session.client.temperature = float(arg)
            session.cfg["temperature"] = float(arg)
            print(f"{DIM}Temperature set to {arg}.{RESET}")
        except ValueError:
            print(f"{RED}Not a number.{RESET}")
    else:
        print(session.cfg.get("temperature"))


# -- skills ----------------------------------------------------------------

@command("skills", "List loaded skills.", "/skills")
def _skills(session: Any, arg: str) -> None:
    if arg:
        return _skill(session, arg)
    print(session.skills.index())


@command("skill", "Show a skill in full.", "/skill <name>")
def _skill(session: Any, arg: str) -> None:
    sk = session.skills.get(arg)
    print(f"\n{sk.full()}\n" if sk else f"{RED}No skill {arg!r}.{RESET}")


@command("reload", "Reload skills from disk.", "/reload")
def _reload(session: Any, arg: str) -> None:
    session.skills.reload()
    print(f"{DIM}Reloaded {len(session.skills.skills)} skill(s).{RESET}")


@command("learn", "Reflect on this session and save skills/memory.", "/learn")
def _learn(session: Any, arg: str) -> None:
    print(f"{DIM}Reflecting…{RESET}")
    transcript = selfimprove.transcript_from_messages(session.agent.messages)
    result = selfimprove.reflect_and_learn(session.ctx, transcript)
    session.skills.reload()
    print(f"{GREEN}{result}{RESET}")


# -- memory ----------------------------------------------------------------

@command("memory", "Search the Obsidian memory vault.", "/memory <query>", aliases=["recall"])
def _memory(session: Any, arg: str) -> None:
    if not arg:
        print(f"{DIM}Vault: {session.memory.vault} "
              f"({len(session.memory.list_notes())} notes){RESET}")
        return
    for r in session.memory.search(arg):
        print(f"  {CYAN}[[{r['title']}]]{RESET}: {r['snippet']}")


@command("remember", "Save a durable fact to memory.", "/remember <text>")
def _remember(session: Any, arg: str) -> None:
    if not arg:
        print(f"{RED}Give something to remember.{RESET}")
        return
    session.memory.write_note(arg[:60], arg, note_type="fact", source="repl")
    print(f"{GREEN}Noted.{RESET}")


@command("vault", "Show the memory vault location and size.", "/vault")
def _vault(session: Any, arg: str) -> None:
    notes = session.memory.list_notes()
    print(f"{session.memory.vault}\n{len(notes)} note(s). Open in Obsidian to browse the graph.")


# -- inspect ---------------------------------------------------------------

@command("tools", "List the tools available to the agent.", "/tools")
def _tools(session: Any, arg: str) -> None:
    for spec in session.agent.registry.specs():
        print(f"  {CYAN}{spec['name']}{RESET} — {spec['description'][:80]}")


@command("system", "Print the current system prompt.", "/system")
def _system(session: Any, arg: str) -> None:
    session.refresh_system_prompt()
    print(session.agent.system)


@command("config", "Show the current config (key redacted).", "/config")
def _config(session: Any, arg: str) -> None:
    safe = dict(session.cfg)
    if safe.get("api_key"):
        safe["api_key"] = "***redacted***"
    print(json.dumps(safe, indent=2, ensure_ascii=False))


# -- autonomy --------------------------------------------------------------

@command("morpheus", "Run the Morpheus self-improvement routine now.",
         "/morpheus", aliases=["nightly"])
def _morpheus(session: Any, arg: str) -> None:
    from .morpheus import run_once
    run_once()
    session.skills.reload()


@command("review", "Review pending approvals inline.", "/review")
def _review(session: Any, arg: str) -> None:
    from .approvals import review_cli
    review_cli()


@command("cron", "List scheduled cron jobs.", "/cron")
def _cron(session: Any, arg: str) -> None:
    from . import cron
    jobs = cron.load_jobs()
    if not jobs:
        print(f"{DIM}No cron jobs.{RESET}")
        return
    for j in jobs:
        print(f"  {j['id']} {int(j.get('hour',0)):02d}:{int(j.get('minute',0)):02d} "
              f"{j.get('type')} — {j.get('name')}")


@command("permission", "Approvals & CLI-agent access level.",
         "/permission [add|remove <category>] | access <workspace|full>")
def _permission(session: Any, arg: str) -> None:
    sub = arg.split()
    auto = list(session.cfg.get("auto_approve", []))
    if len(sub) == 2 and sub[0] == "access" and sub[1] in ("workspace", "full"):
        session.cfg["cli_access"] = sub[1]
        session.client.cli_access = sub[1]   # apply to the live session
        config.save_config(session.cfg)
        if sub[1] == "full":
            print(f"{YELLOW}⚠ 'full': the CLI agent now bypasses all approvals & "
                  f"sandbox — it can run ANY command / edit ANY file.{RESET}")
    elif len(sub) == 2 and sub[0] in ("add", "remove"):
        cat = sub[1]
        if sub[0] == "add" and cat in ("shell", "cron"):
            print(f"{YELLOW}⚠ auto-approving '{cat}' lets the unattended nightly "
                  f"routine run it without asking (incl. shell at 04:00).{RESET}")
        if sub[0] == "add" and cat not in auto:
            auto.append(cat)
        elif sub[0] == "remove" and cat in auto:
            auto.remove(cat)
        session.cfg["auto_approve"] = auto
        config.save_config(session.cfg)
    print(f"{DIM}Auto-approved: {', '.join(auto) or '(none)'} · "
          f"CLI access: {session.cfg.get('cli_access', 'workspace')} "
          f"(/permission access workspace|full){RESET}")


# -- session persistence ---------------------------------------------------

@command("save", "Save the current conversation.", "/save [name]")
def _save(session: Any, arg: str) -> None:
    name = arg or datetime.now().strftime("%Y%m%d-%H%M%S")
    path = config.sessions_dir() / f"{name}.json"
    path.write_text(json.dumps(session.agent.messages, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    print(f"{DIM}Saved to {path}{RESET}")


@command("load", "Load a saved conversation.", "/load <name>")
def _load(session: Any, arg: str) -> None:
    if not arg:
        print(f"{RED}Give a session name (see /sessions).{RESET}")
        return
    path = config.sessions_dir() / f"{arg}.json"
    if not path.is_file():
        print(f"{RED}No session {arg!r}.{RESET}")
        return
    session.agent.messages = json.loads(path.read_text(encoding="utf-8"))
    print(f"{DIM}Loaded {arg} ({len(session.agent.messages)} messages).{RESET}")


@command("sessions", "List saved conversations.", "/sessions")
def _sessions(session: Any, arg: str) -> None:
    files = sorted(config.sessions_dir().glob("*.json"), reverse=True)
    if not files:
        print(f"{DIM}No saved sessions.{RESET}")
        return
    for f in files[:30]:
        print(f"  {f.stem}")


# -- system / maintenance --------------------------------------------------

@command("update", "Update birkin to the latest version.", "/update")
def _update(session: Any, arg: str) -> None:
    import subprocess
    root = Path(__file__).resolve().parent.parent  # repo root if source checkout
    if (root / ".git").exists():
        print(f"{DIM}git pull in {root}…{RESET}")
        proc = subprocess.run(["git", "-C", str(root), "pull", "--ff-only"],
                              capture_output=True, text=True, errors="replace")
        print(proc.stdout or proc.stderr)
        print(f"{DIM}Restart birkin to load changes.{RESET}")
    else:
        print("Installed (not a source checkout). Update with your installer, e.g.:")
        print(f"  {CYAN}uv tool install --force git+https://github.com/ashmoonori-afk/birkin{RESET}")
        print("  or re-run the install one-liner from the README.")


@command("quit", "Leave birkin.", "/quit", aliases=["exit", "q"])
def _quit(session: Any, arg: str) -> str:
    return "exit"


# -- shared with repl ------------------------------------------------------

def sys_write(session: Any, text: str) -> None:
    """Send `text` to the agent and stream the reply (used by /retry)."""
    import sys
    sys.stdout.write(f"\n{CYAN}birkin{RESET} > ")
    sys.stdout.flush()
    try:
        session.ask(text, on_text=ui.stream_text)
        sys.stdout.write("\n")
        store.append_activity(f"chat: {text[:120]}")
    except Exception as exc:
        print(f"\n{RED}Error: {exc}{RESET}")
