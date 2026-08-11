"""Slash-command system for the birkin REPL.

A small registry so commands stay easy to add and self-documenting. Each
``Command`` carries a summary + usage for ``/help``. Handlers receive
``(session, arg)`` and return ``"exit"`` to leave the REPL, or anything else to
continue.

This set is intentionally broader and more detailed than hermes' built-ins.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass, field
from datetime import datetime
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

# Commands grouped by domain so /help is scannable, not a flat 30-line dump
# (gh-dash/lazygit group contextual keys). The registry stays the single
# source: any command not listed here falls into "기타" so nothing is hidden.
_HELP_GROUPS: list[tuple[str, list[str]]] = [
    ("세션·대화", ["new", "retry", "undo", "rollback", "compact", "clear",
                 "save", "load", "sessions", "status", "dash", "agents",
                 "attach", "send"]),
    ("모델", ["model", "models", "provider", "temp"]),
    ("기억", ["memory", "remember", "vault", "learn"]),
    ("스킬·도구", ["skills", "skill", "reload", "tools", "system", "mcp",
                 "details"]),
    ("운영·승인", ["goal", "review", "cron", "permission", "config",
                 "morpheus", "update"]),
    ("페르소나·인터뷰", ["soul", "personality", "neurosis", "odyssey"]),
    ("게이트웨이", ["restart-gateway", "hard-restart"]),
    ("종료·도움", ["help", "quit"]),
]


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

    print(f"{BOLD}Slash commands{RESET} {DIM}(/help <name> 으로 상세 · "
          f"? 로 다시 열기){RESET}")
    grouped: set[str] = set()

    def _row(name: str) -> None:
        c = _REGISTRY[name]
        al = (f" {DIM}({', '.join('/' + a for a in c.aliases)}){RESET}"
              if c.aliases else "")
        # ASCII command names -> left-pad with len() aligns; the Korean summary
        # is the last column, so there is nothing to its right to misalign.
        print(f"  {CYAN}/{name}{RESET}{al}{' ' * max(1, 13 - len(name))}"
              f"{c.summary}")

    for title, names in _HELP_GROUPS:
        present = [n for n in names if n in _REGISTRY]
        if not present:
            continue
        print(f"\n{BOLD}{title}{RESET}")
        for n in present:
            _row(n)
            grouped.add(n)

    leftover = sorted(n for n in _REGISTRY if n not in grouped)
    if leftover:
        print(f"\n{BOLD}기타{RESET}")
        for n in leftover:
            _row(n)


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


@command("rollback", "Undo file changes from an earlier checkpoint.",
         "/rollback [N | diff N | N <file>]")
def _rollback(session: Any, arg: str) -> None:
    """Restore workspace files snapshotted before a turn.

    Bare lists checkpoints; ``diff N`` previews; ``N`` restores everything from
    that checkpoint; ``N <file>`` restores just one file.
    """
    mgr = getattr(session.ctx, "checkpoints", None)
    if mgr is None or not getattr(mgr, "enabled", False):
        print(f"{DIM}Checkpoints are disabled (config \"checkpoints\").{RESET}")
        return
    cwd = session.ctx.cwd
    entries = mgr.list_checkpoints(cwd)
    if not entries:
        print(f"{DIM}No checkpoints yet for {cwd}.{RESET}")
        return

    parts = arg.split(maxsplit=2)
    if not parts:
        print(f"{BOLD}Checkpoints for {cwd}{RESET}")
        for i, e in enumerate(entries, 1):
            print(f"  {i:>2}. {e['short']}  {e['date'][:19]}  {e['reason']}")
        print(f"{DIM}  /rollback diff 1   preview · "
              f"/rollback 1   restore · /rollback 1 path/to/file{RESET}")
        return

    preview = parts[0].lower() == "diff"
    if preview:
        parts = parts[1:]
    if not parts or not parts[0].isdigit():
        print(f"{RED}Give a checkpoint number from /rollback.{RESET}")
        return
    n = int(parts[0])
    if not 1 <= n <= len(entries):
        print(f"{RED}No checkpoint {n} (have 1..{len(entries)}).{RESET}")
        return
    entry = entries[n - 1]

    if preview:
        text = mgr.diff(cwd, entry["hash"])
        if not text.strip():
            print(f"{DIM}No differences from that checkpoint.{RESET}")
            return
        lines = text.splitlines()
        print("\n".join(lines[:80]))
        if len(lines) > 80:
            print(f"{DIM}… {len(lines) - 80} more lines{RESET}")
        return

    target = parts[1] if len(parts) > 1 else None
    ok, message = mgr.restore(cwd, entry["hash"], target)
    if not ok:
        print(f"{RED}Rollback failed: {message}{RESET}")
        return
    print(f"{GREEN}{message} ({entry['short']}, {entry['reason']}).{RESET}")
    print(f"{DIM}A checkpoint was taken first, so this is itself undoable. "
          f"Files created after the checkpoint are left in place.{RESET}")
    idx = _last_user_index(session.agent.messages)
    if idx >= 0:
        session.agent.messages = session.agent.messages[:idx]
        print(f"{DIM}Dropped the last exchange so the chat matches the "
              f"files.{RESET}")


@command("compact", "Summarize the conversation to shrink context.", "/compact",
         aliases=["compress"])
def _compact(session: Any, arg: str) -> None:
    before = len(session.agent.messages)
    if before < 6:
        print(f"{DIM}Conversation is already short.{RESET}")
        return
    print(f"{DIM}Summarizing…{RESET}")
    # Shares the automatic path: keeps the opening exchange and the recent
    # tail, and folds any previous summary in rather than starting over.
    session.agent._compact_floor = 0   # an explicit ask overrides the latch
    if not session.agent.compact_now("manual"):
        print(f"{YELLOW}Nothing to compact (or the summarizer failed) — "
              f"history left untouched.{RESET}")
        return
    print(f"{GREEN}Compacted {before} → {len(session.agent.messages)} "
          f"messages.{RESET}")


@command("clear", "Clear the screen.", "/clear")
def _clear(session: Any, arg: str) -> None:
    import os
    os.system("cls" if os.name == "nt" else "clear")


# -- model / provider ------------------------------------------------------

def _warn_if_key_missing(session: Any) -> None:
    """Warn (don't block) if the just-selected provider needs an API key we
    don't have — the 'picked an API model but only have a CLI login' case, which
    would otherwise fail confusingly on the next turn."""
    prov = session.cfg.get("provider")
    if prov in ("anthropic", "openai"):
        key = config.get_api_key(session.cfg)
        if not key or key == "cli":
            env = config.PROVIDER_API_KEY_ENV.get(prov, "ANTHROPIC_API_KEY")
            print(f"{YELLOW}  heads up: no API key for {prov} — set {env}, "
                  f"or pick a local CLI model instead.{RESET}")


def _set_model(session: Any, arg: str) -> None:
    """Apply a ``/model`` / ``/models`` argument live.

    A number (as shown in the list) or a listed model name resolves to a real
    model and switches the PROVIDER too (via apply_selection) — so picking a
    claude-cli entry actually runs Claude Code, not codex-with-a-claude-id. An
    unknown string is set raw against the current provider (advanced)."""
    from . import models as models_mod
    found = models_mod.discover(session.cfg)
    chosen = models_mod.resolve(found, arg)
    if chosen is not None:
        models_mod.apply_selection(session.cfg, chosen)
        label = f"{chosen.id} [{session.cfg.get('provider')}]"
    else:
        session.cfg["model"] = arg    # raw: keep current provider (advanced)
        label = f"{arg} (raw · provider stays {session.cfg.get('provider')})"
    config.save_config(session.cfg)
    session.reload_client()           # rebuild the live client for the new backend
    print(f"{GREEN}✓ model → {label} — applies now.{RESET}")
    _warn_if_key_missing(session)


@command("model", "Show the model, or set one: /model <number|name>.", "/model [name]")
def _model(session: Any, arg: str) -> None:
    arg = arg.strip()
    if arg:
        _set_model(session, arg)
    else:
        print(session.cfg.get("model"))


@command("models", "Pick a model (↑/↓, Enter), or /models <number|name>.",
         "/models [number|name]")
def _models(session: Any, arg: str) -> None:
    from . import models as models_mod
    arg = arg.strip()
    if arg:
        _set_model(session, arg)
        return
    chosen = models_mod.pick_interactive(session.cfg)   # arrow picker; applies to cfg
    if chosen is None:
        print(f"{DIM}(no change){RESET}")
        return
    config.save_config(session.cfg)
    session.reload_client()
    print(f"{GREEN}✓ model → {chosen.id} [{session.cfg.get('provider')}] "
          f"— applies now.{RESET}")
    _warn_if_key_missing(session)


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


@command("status", "Show the live status line (model · daemon · budget · 대기).",
         "/status")
def _status(session: Any, arg: str) -> None:
    from . import statusline
    print(statusline.render(session.cfg))


@command("dash", "Full-screen mission control (세션·크론·승인·기억).",
         "/dash [--plain|--json]", aliases=["dashboard"])
def _dash(session: Any, arg: str) -> None:
    from . import dash
    a = arg.strip().lower()
    dash.run(session, plain=(a == "--plain"), as_json=(a == "--json"))


def _agent_run_rows() -> list[tuple[dict[str, Any], int]]:
    from . import agentruns
    rows: list[tuple[dict[str, Any], int]] = []

    def visit(run: dict[str, Any], depth: int) -> None:
        rows.append((run, depth))
        for child in run.get("children", []):
            visit(child, depth + 1)

    for root in agentruns.list_runs():
        visit(root, 0)
    return rows


def _find_agent_run(run_id: str) -> dict[str, Any] | None:
    from . import agentruns
    exact = agentruns.get_run(run_id)
    if exact is not None:
        return exact
    matches = [run for run, _depth in _agent_run_rows()
               if run["id"].startswith(run_id)]
    return matches[0] if len(matches) == 1 else None


@command("agents", "List durable parent/child agent runs.", "/agents")
def _agents(session: Any, arg: str) -> None:
    rows = _agent_run_rows()
    if not rows:
        print(f"{DIM}No agent runs.{RESET}")
        return
    print(f"{BOLD}Agent runs{RESET}")
    for run, depth in rows:
        prefix = "  " + "  " * depth
        age = int(run.get("heartbeat_age", 0))
        print(f"{prefix}{CYAN}{run['id'][:8]}{RESET}  "
              f"{run['status']:<8}  {run['task'][:36]:<36}  "
              f"{DIM}hb {age}s ago{RESET}")


@command("attach", "Attach to a durable agent run and follow it live.",
         "/attach <run-id>")
def _attach(session: Any, arg: str) -> None:
    from . import agentruns
    run = _find_agent_run(arg.strip()) if arg.strip() else None
    if run is None:
        print(f"{RED}No run {arg.strip()!r}. See /agents.{RESET}")
        return
    print(f"{BOLD}{run['id']}{RESET}  {run['status']}")
    print(run["task"])
    if run["status"] == "running":
        print(f"{DIM}following — Ctrl-C detaches and leaves it running{RESET}")
    try:
        final = agentruns.follow(run["id"],
                                 lambda line: print(f"{DIM}  {line}{RESET}"))
    except KeyboardInterrupt:
        print(f"\n{DIM}Detached. {run['id'][:8]} keeps running.{RESET}")
        return
    if final is None:
        print(f"{RED}Run {run['id'][:8]} is gone.{RESET}")
        return
    if final["status"] not in ("running", run["status"]):
        # A stale record still reads "running"; the header already said so.
        print(f"{BOLD}{final['status']}{RESET}")
    if final.get("result"):
        print(f"\n{final['result']}")


@command("send", "Queue a message for a running agent.",
         "/send <run-id> <message>")
def _send(session: Any, arg: str) -> None:
    from . import agentruns
    parts = arg.split(maxsplit=1)
    if len(parts) != 2 or not parts[1].strip():
        print(f"{RED}Usage: /send <run-id> <message>{RESET}")
        return
    run = _find_agent_run(parts[0])
    if run is None or not agentruns.append_message(run["id"], parts[1].strip()):
        print(f"{RED}No run {parts[0]!r}. See /agents.{RESET}")
        return
    print(f"{GREEN}Queued for {run['id'][:8]}.{RESET}")


@command("details", "Toggle verbose tool traces (full input + result snippet).",
         "/details [on|off]")
def _details(session: Any, arg: str) -> None:
    a = arg.strip().lower()
    on = True if a in ("on", "1", "true") else False if a in (
        "off", "0", "false") else not ui.details_on()
    ui.set_details(on)
    print(f"{DIM}툴 트레이스 상세 {'켜짐' if on else '꺼짐'}.{RESET}")


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


@command("goal", "Persist a session goal with an optional verifier.",
         "/goal set <objective> [--gate \"command\"] | show | pause | done")
def _goal(session: Any, arg: str) -> None:
    from . import goals
    try:
        parts = shlex.split(arg)
    except ValueError as exc:
        print(f"{RED}Invalid /goal arguments: {exc}{RESET}")
        return
    if not parts:
        print(f"{DIM}Usage: /goal set <objective> [--gate \"command\"] "
              f"| show | pause | done{RESET}")
        return

    action = parts.pop(0).lower()
    if action == "show":
        status = goals.render_status()
        print(status or f"{DIM}No active goal.{RESET}")
        return
    if action == "pause":
        state = goals.pause()
        print(f"{DIM}Goal paused.{RESET}" if state else
              f"{DIM}No active goal.{RESET}")
        return
    if action == "done":
        state = goals.get_active()
        if state is None:
            print(f"{DIM}No active goal.{RESET}")
            return
        final, outcome = goals.request_completion(state, session.cfg)
        if outcome == "queued":
            print(f"{DIM}Verifier queued for approval: {state.gate_cmd}{RESET}")
            print(f"{RED}Goal stays open until it passes — approve it with "
                  f"/review, then run /goal done again.{RESET}")
            return
        if outcome == "failed":
            print(f"{RED}Verifier failed; goal stays open.{RESET}")
            tail = str((final.gate_last or {}).get("output_tail") or "").strip()
            if tail:
                print(f"{DIM}{tail[-500:]}{RESET}")
            return
        print(f"{GREEN}Goal done: {state.objective}{RESET}")
        return
    if action != "set":
        print(f"{RED}Unknown /goal action {action!r}.{RESET}")
        return

    objective: list[str] = []
    gate: str | None = None
    i = 0
    while i < len(parts):
        part = parts[i]
        if part == "--gate":
            if i + 1 >= len(parts):
                print(f"{RED}{part} needs a value.{RESET}")
                return
            gate = parts[i + 1]
            i += 2
            continue
        if part.startswith("--"):
            print(f"{RED}Unknown /goal option {part!r}.{RESET}")
            return
        objective.append(part)
        i += 1
    try:
        state = goals.set_goal(" ".join(objective), gate=gate)
    except ValueError as exc:
        print(f"{RED}{exc}{RESET}")
        return
    print(f"{GREEN}Goal set: {state.objective}{RESET}")
    print(goals.render_status())
    if state.gate_cmd:
        print(f"{DIM}The verifier runs through the approval queue "
              f"when /goal done is used.{RESET}")


@command("cron", "List scheduled cron jobs.", "/cron")
def _cron(session: Any, arg: str) -> None:
    from . import cron
    jobs = cron.load_jobs()
    if not jobs:
        print(f"{DIM}No cron jobs.{RESET}")
        return
    for j in jobs:
        print(f"  {j['id']} {cron.schedule_display(j)} "
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
                    f"routine run it without asking (incl. shell at the "
                    f"configured Morpheus time).{RESET}")
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


@command("sessions", "List or search saved conversations.",
         "/sessions [query] [--since 30d] [--from telegram] [--model name]")
def _sessions(session: Any, arg: str) -> None:
    # Hide reserved auto__* transcripts (auto-saved for memory extraction); they
    # are not meant for manual /load and would flood this list.
    if arg.strip():
        _sessions_search(arg)
        return
    files = [f for f in sorted(config.sessions_dir().glob("*.json"), reverse=True)
             if not transcripts.is_auto(f.stem)]
    if not files:
        print(f"{DIM}No saved sessions.{RESET}")
        return
    for f in files[:30]:
        print(f"  {f.stem}")


def _sessions_search(arg: str) -> None:
    from .tools import sessions as sessions_tool
    try:
        parts = shlex.split(arg)
    except ValueError as exc:
        print(f"{RED}Invalid /sessions arguments: {exc}{RESET}")
        return
    query: list[str] = []
    filters: dict[str, str | None] = {
        "since": None, "channel": None, "model": None}
    aliases = {"--since": "since", "--from": "channel",
               "--channel": "channel", "--model": "model"}
    i = 0
    while i < len(parts):
        part = parts[i]
        key = aliases.get(part)
        if key is not None:
            if i + 1 >= len(parts):
                print(f"{RED}{part} needs a value.{RESET}")
                return
            filters[key] = parts[i + 1]
            i += 2
            continue
        if part.startswith("--"):
            print(f"{RED}Unknown /sessions option {part!r}.{RESET}")
            return
        query.append(part)
        i += 1
    if not query:
        print(f"{RED}Give a search query, or use bare /sessions to list.{RESET}")
        return
    try:
        hits = sessions_tool.search_sessions(
            " ".join(query), since=filters["since"],
            channel=filters["channel"], model=filters["model"])
    except ValueError as exc:
        print(f"{RED}{exc}{RESET}")
        return
    if not hits:
        print(f"{DIM}No matching sessions.{RESET}")
        return
    for hit in hits:
        model = f" · {hit['model']}" if hit.get("model") else ""
        print(f"  {CYAN}{hit['session']}{RESET} · {hit['date'][:10]} · "
              f"{hit['channel']}{model} · score {hit['score']:.3f}")
        if hit.get("snippet"):
            print(f"    {DIM}{hit['snippet']}{RESET}")


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


# -- odyssey (goal-completion cycle) ---------------------------------------

@command("odyssey", "Goal-completion cycle: plan, critique, execute, verify.",
         "/odyssey <goal>", aliases=["ultrawork", "ulw"])
def _odyssey(session: Any, arg: str) -> None:
    from . import odyssey
    goal = arg.strip()
    if not goal:
        print(f"{DIM}Give a goal: /odyssey <goal>{RESET}")
        return
    s = odyssey.seed(goal, cfg=session.cfg)
    head = "Resuming" if s["resume"] else "Starting"
    print(f"{DIM}{head} odyssey '{s['slug']}' · plan → {s['boulder_path']}{RESET}")
    sys_write(session, odyssey.start_prompt(s))


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
