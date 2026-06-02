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

from . import config, selfimprove, store, transcripts, ui
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


@command("models", "List models, or select one: /models [name].", "/models [name]")
def _models(session: Any, arg: str) -> None:
    from . import models as models_mod
    name = arg.strip()
    if name:  # select — applies live in the REPL (no restart needed here)
        session.cfg["model"] = name
        session.client.model = name
        config.save_config(session.cfg)
        print(f"{GREEN}Model set to {name} (applies now).{RESET}")
        return
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
         "/permission [add|remove <category>] | access <workspace|full> | "
         "unattended-full <on|off>", aliases=["permissions"])
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
    elif len(sub) == 2 and sub[0] == "unattended-full" and sub[1] in ("on", "off"):
        # Let the UNATTENDED nightly Morpheus run keep cli_access "full" (the
        # reachable gateway is ALWAYS workspace regardless). Default off.
        session.cfg["allow_unattended_full"] = (sub[1] == "on")
        config.save_config(session.cfg)
        if sub[1] == "on":
            print(f"{YELLOW}⚠ unattended-full ON: the nightly Morpheus run may now "
                  f"bypass sandbox/approvals (needs cli_access 'full' too). The "
                  f"gateway stays sandboxed.{RESET}")
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
    uf = "on" if session.cfg.get("allow_unattended_full") else "off"
    print(f"{DIM}Auto-approved: {', '.join(auto) or '(none)'} · "
          f"CLI access: {session.cfg.get('cli_access', 'workspace')} · "
          f"unattended-full: {uf} "
          f"(/permission access workspace|full · unattended-full on|off){RESET}")


# -- session persistence ---------------------------------------------------

@command("save", "Save the current conversation.", "/save [name]")
def _save(session: Any, arg: str) -> None:
    name = arg or datetime.now().strftime("%Y%m%d-%H%M%S")
    if transcripts.is_auto(name):
        print(f"{RED}Names starting with '{transcripts.AUTO_PREFIX}' are reserved "
              f"for auto-saved transcripts. Pick another name.{RESET}")
        return
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
    # Hide reserved auto__* transcripts (auto-saved for memory extraction); they
    # are not meant for manual /load and would flood this list.
    files = [f for f in sorted(config.sessions_dir().glob("*.json"), reverse=True)
             if not transcripts.is_auto(f.stem)]
    if not files:
        print(f"{DIM}No saved sessions.{RESET}")
        return
    for f in files[:30]:
        print(f"  {f.stem}")


# -- gateway ---------------------------------------------------------------

def _gateway_post(cfg: dict, text: str) -> str:
    """Send *text* to the local gateway via HTTP and return the reply."""
    import urllib.error
    import urllib.request
    port = cfg.get("gateway_port", 8788)
    url = f"http://127.0.0.1:{port}/message"
    body = json.dumps({"text": text, "session": "repl"}).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data.get("reply", "")
    except urllib.error.URLError as exc:
        return f"{RED}Gateway not reachable ({exc}). Is `birkin gateway` running?{RESET}"


@command("restart-gateway", "Soft-restart the gateway (reload config/persona/memory).",
         "/restart-gateway", aliases=["restart"])
def _restart_gateway(session: Any, arg: str) -> None:
    reply = _gateway_post(session.cfg, "/restart-gateway")
    print(reply)


@command("hard-restart", "Hard-restart the gateway (picks up code changes too).",
         "/hard-restart", aliases=["restart-hard"])
def _hard_restart(session: Any, arg: str) -> None:
    reply = _gateway_post(session.cfg, "/hard-restart")
    print(reply)


# -- system / maintenance --------------------------------------------------

@command("update", "Update birkin to the latest version (fast-forward; shows version).",
         "/update", aliases=["upgrade"])
def _update(session: Any, arg: str) -> None:
    from .updater import update
    result = update()
    print(result["message"])
    if result.get("updated"):
        print(f"{DIM}Restart birkin to load the new code.{RESET}")


@command("quit", "Leave birkin.", "/quit", aliases=["exit", "q"])
def _quit(session: Any, arg: str) -> str:
    return "exit"


# -- shared with repl ------------------------------------------------------

# -- persona ---------------------------------------------------------------

@command("soul", "Show birkin's persona (or its file path).", "/soul [path|reset]",
         aliases=["persona"])
def _soul(session: Any, arg: str) -> None:
    from . import persona
    a = arg.strip().lower()
    if a == "path":
        print(persona.soul_path())
        return
    if a == "reset":
        persona.seed_default(force=True)
        print(f"{GREEN}Persona reset to the default warm voice.{RESET}")
        return
    text = persona.read_soul()
    if not text:
        print(f"{DIM}No SOUL.md set — using the built-in default voice. "
              f"Create {persona.soul_path()} or use /personality.{RESET}")
    else:
        print(f"{DIM}{persona.soul_path()}{RESET}\n{text}")


@command("personality", "Switch persona to a built-in preset.",
         "/personality [warm|concise|mentor|direct]")
def _personality(session: Any, arg: str) -> None:
    from . import persona
    name = arg.strip().lower()
    if not name:
        cur = persona.read_soul()
        print(f"Presets: {', '.join(persona.PRESETS)}")
        print(f"{DIM}Current persona:\n{cur or '(built-in default)'}{RESET}")
        return
    preset = persona.PRESETS.get(name)
    if not preset:
        print(f"{RED}Unknown preset {name!r}. Choose: {', '.join(persona.PRESETS)}.{RESET}")
        return
    persona.write_soul(preset)
    print(f"{GREEN}Persona set to '{name}'. Applies immediately (incl. gateway).{RESET}")


# -- MCP (company tool connections) ----------------------------------------

@command("mcp", "List MCP servers (company tools). The gateway inherits these.",
         "/mcp")
def _mcp(session: Any, arg: str) -> None:
    from . import mcp as mcp_mod
    servers, err = mcp_mod.list_servers()
    if err:
        print(f"{RED}{err}{RESET}")
        return
    if not servers:
        print(f"{DIM}No MCP servers. Add one with `birkin mcp add <name> "
              f"<command-or-url>`.{RESET}")
        return
    print(f"{BOLD}MCP servers{RESET} {DIM}(the gateway uses these automatically){RESET}")
    for s in servers:
        color = GREEN if s.connected else YELLOW
        print(f"  {color}{'✓' if s.connected else '•'}{RESET} {s.name} "
              f"{DIM}— {s.status}{RESET}")


# -- neurosis (deep interview) ---------------------------------------------

@command("neurosis", "Deep interview: Socratic clarity-gating before acting.",
         "/neurosis [--quick|--standard|--deep] <idea>", aliases=["interview"])
def _neurosis(session: Any, arg: str) -> None:
    from . import neurosis
    resolution = None
    kept: list[str] = []
    for tok in arg.split():
        if tok in ("--quick", "--standard", "--deep"):
            resolution = tok[2:]
        else:
            kept.append(tok)
    idea = " ".join(kept).strip()
    seed = neurosis.seed_or_resume(idea, cfg=session.cfg, resolution=resolution)
    if seed is None:
        print(f"{DIM}Give an idea: /neurosis <vague idea>  "
              f"(or run /neurosis with no idea to resume an active interview).{RESET}")
        return
    if seed["resume"]:
        print(f"{DIM}Resuming neurosis interview '{seed['slug']}'…{RESET}")
    else:
        print(f"{DIM}neurosis '{seed['slug']}' · threshold {seed['threshold_percent']} "
              f"({seed['threshold_source']}) · spec → {seed['spec_path']}{RESET}")
    sys_write(session, neurosis.start_prompt(seed))


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
