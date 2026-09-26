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
import threading
import time
from dataclasses import dataclass, field, is_dataclass, replace
from datetime import datetime
from typing import Any, Callable, Optional, cast

from . import config, selfimprove, store, transcripts, ui
from .persistence_safety import unsafe_persistence_reason
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
                 "sessions", "status", "summon", "agents", "attach", "send"]),
    ("모델", ["model", "provider", "temp"]),
    ("기억", ["memory", "learn"]),
    ("스킬·도구", ["skills", "tools", "system", "mcp", "details"]),
    ("운영·승인", ["work", "goal", "review", "cron", "permission",
                 "config", "morpheus", "update"]),
    ("페르소나·인터뷰", ["persona", "profile", "neurosis", "odyssey"]),
    ("게이트웨이", ["restart"]),
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
    print(f" {DIM}edit: Ctrl-W delete word · Ctrl-U/Ctrl-K clear to start/end{RESET}")
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


@command("model", "Pick a model (↑/↓, Enter), or set one: /model <number|name>.",
         "/model [number|name]", aliases=["models"])
def _model(session: Any, arg: str) -> None:
    # Two modes only, matching hermes: a bare /model picks, /model <name> sets.
    # There is deliberately no "print the current model" mode — the status line
    # already carries it. Without a terminal (gateway, telegram) menu.select
    # degrades to a printed list and returns None, so nothing blocks.
    arg = arg.strip()
    if arg:
        _set_model(session, arg)
        return
    from . import models as models_mod
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

@command("skills", "List skills, show one (/skills <name>), or /skills reload.",
         "/skills [name|reload]")
def _skills(session: Any, arg: str) -> None:
    name = arg.strip()
    if not name:
        print(session.skills.index())
        return
    if name.lower() == "reload":
        session.skills.reload()
        print(f"{DIM}Reloaded {len(session.skills.skills)} skill(s).{RESET}")
        return
    sk = session.skills.get(name)
    print(f"\n{sk.full()}\n" if sk else f"{RED}No skill {name!r}.{RESET}")


@command("learn", "Reflect on this session and save skills/memory.", "/learn")
def _learn(session: Any, arg: str) -> None:
    print(f"{DIM}Reflecting…{RESET}")
    transcript = selfimprove.transcript_from_messages(session.agent.messages)
    result = selfimprove.reflect_and_learn(session.ctx, transcript)
    session.skills.reload()
    print(f"{GREEN}{result}{RESET}")


# -- memory ----------------------------------------------------------------

@command("memory", "Search memory; /memory save <text>; /memory where.",
         "/memory [query|save <text>|where]", aliases=["recall"])
def _memory(session: Any, arg: str) -> None:
    # One command for the vault: searching, saving, and locating it were three
    # names for one concern. A bare /memory reports where the vault is, which is
    # what the old /vault did.
    verb, _, rest = arg.strip().partition(" ")
    rest = rest.strip()
    if verb.lower() == "save":
        if not rest:
            print(f"{RED}Give something to remember: /memory save <text>.{RESET}")
            return
        unsafe = unsafe_persistence_reason(rest[:60], rest)
        if unsafe is not None:
            print(f"{RED}Persistence refused: {unsafe}.{RESET}")
            return
        session.memory.write_note(rest[:60], rest, note_type="fact", source="repl")
        print(f"{GREEN}Noted.{RESET}")
        return
    if not arg.strip() or (verb.lower() == "where" and not rest):
        notes = session.memory.list_notes()
        print(f"{session.memory.vault}\n{len(notes)} note(s). "
              f"Open in Obsidian to browse the graph.")
        return
    for r in session.memory.search(arg.strip()):
        print(f"  {CYAN}[[{r['title']}]]{RESET}: {r['snippet']}")


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


@command("work", "Focus the unified tasks/runs workbench.",
         "/work [--plain|--json]", aliases=["workbench"])
def work_command(session: object, arg: str) -> None:
    a = arg.strip().lower()
    if a not in {"", "--plain", "--json"}:
        print("usage: /work [--plain|--json]")
        return
    focus = getattr(session, "workspace_focus", None)
    if callable(focus):
        callback = cast(Callable[[str], object], focus)
        _ = callback("tasks_runs")
        suffix = " Legacy format flag ignored." if a else ""
        print(f"/work is the unified workbench; focused tasks/runs.{suffix}")
        return
    print("/work now opens inside `birkin chat`; start the unified workspace.")


_RUN_STATUS_LABELS = {
    "running": "실행 중",
    "done": "완료",
    "error": "실패",
    "stale": "응답 없음",
}
_AGENTS_RECENT_ROOTS = 20
_AGENTS_HINT = "/attach <ID> 따라가기 · /send <ID> <메시지> 방향 바꾸기"
_RUN_ID_HINT = "ID는 /agents 에서 볼 수 있어요."
# A progress-trail line is "<event> <tool name>"; show what it means.
_TRAIL_TEXT = {
    "steer": "↪ 보낸 메시지를 반영했어요",
    "compact": "대화 내용을 요약해 정리했어요",
    "warning": "! 경고가 있었어요",
    "ooda_stall": "↻ 진행이 막혀 방향을 다시 잡았어요",
}


def _flat(text: object) -> str:
    """One terminal line of possibly model- or file-authored text.

    Whitespace collapses and control/format characters become visible
    escapes, so a task or title cannot move the cursor or write the
    clipboard (an OSC 52 sequence) on the user's terminal.
    """
    return ui.printable(" ".join(str(text or "").split()))


def _agent_run_rows(roots: list[dict[str, Any]] | None = None,
                    ) -> list[tuple[dict[str, Any], int]]:
    from . import agentruns
    rows: list[tuple[dict[str, Any], int]] = []

    def visit(run: dict[str, Any], depth: int) -> None:
        rows.append((run, depth))
        for child in run.get("children", []):
            visit(child, depth + 1)

    for root in (agentruns.list_runs() if roots is None else roots):
        visit(root, 0)
    return rows


def _match_agent_runs(key: str) -> list[dict[str, Any]]:
    """Runs whose id is ``key``, else whose id starts with it.

    Rows come from list_runs, so a full id and a prefix see the same status
    (a dead worker reads "stale" either way) and heartbeat age.
    """
    runs = [run for run, _depth in _agent_run_rows()]
    exact = [run for run in runs if run["id"] == key]
    return exact or [run for run in runs if run["id"].startswith(key)]


def _resolve_run(key: str, usage: str) -> dict[str, Any] | None:
    """The one run ``key`` names, or None after telling the user why not."""
    if not key:
        print(f"{RED}사용법: {usage}{RESET}")
        print(f"{DIM}{_RUN_ID_HINT}{RESET}")
        return None
    matches = _match_agent_runs(key)
    shown = ui.fit(_flat(key), 40)
    if not matches:
        print(f"{RED}'{shown}' 실행을 찾을 수 없어요. "
              f"/agents 로 ID를 확인하세요.{RESET}")
        return None
    if len(matches) > 1:
        print(f"{RED}'{shown}'(으)로 시작하는 실행이 {len(matches)}개예요. "
              f"ID를 더 길게 입력하세요.{RESET}")
        return None
    return matches[0]


def _agent_titles() -> dict[str, str]:
    from . import summon
    roster, _rejected = summon.load_roster()
    return {name: spec.title for name, spec in roster.items()}


def _run_title(run: dict[str, Any], titles: dict[str, str]) -> str:
    agent = run.get("agent")
    if not agent:
        return ""
    return str(titles.get(agent) or run.get("agent_title") or agent)


def _run_label(run: dict[str, Any]) -> str:
    if run.get("status") == "running" and run.get("control_state") == "blocked":
        return "일시정지"
    return _RUN_STATUS_LABELS.get(str(run.get("status")), "알 수 없음")


def _run_time(run: dict[str, Any]) -> str:
    from . import agentruns
    status = run.get("status")
    if status == "running":
        return f"{ui.duration_ko(agentruns.elapsed_seconds(run))}째"
    if status == "stale":
        # list_runs computes heartbeat_age for every row.
        return f"신호 끊김 {ui.duration_ko(run.get('heartbeat_age', 0))}"
    return f"{ui.duration_ko(agentruns.elapsed_seconds(run))} 걸림"


@command("agents", "에이전트 실행 목록과 상태를 봐요.", "/agents [all]")
def _agents(session: Any, arg: str) -> None:
    import shutil

    from . import agentruns
    choice = arg.strip().lower()
    if choice not in ("", "all"):
        print(f"{RED}사용법: /agents [all]{RESET}")
        return
    roots = agentruns.list_runs()
    if not roots:
        print(f"{DIM}아직 실행한 에이전트가 없어요. "
              f"/summon 으로 전문가 에이전트를 불러 보세요.{RESET}")
        return
    hidden = 0
    if choice != "all" and len(roots) > _AGENTS_RECENT_ROOTS:
        hidden = len(_agent_run_rows(roots[:-_AGENTS_RECENT_ROOTS]))
        roots = roots[-_AGENTS_RECENT_ROOTS:]
    titles = _agent_titles()
    cols = shutil.get_terminal_size((100, 30)).columns
    print(f"{BOLD}에이전트 실행{RESET}")
    for run, depth in _agent_run_rows(roots):
        # Display-width padding keeps a Hangul row aligned with an ASCII one;
        # the task goes last so nothing to its right can be pushed out.
        prefix = "  " + "  " * depth
        label = ui.pad(_run_label(run), 10)
        when = ui.pad(_run_time(run), 20)
        used = ui.cell_width(f"{prefix}{run['id'][:8]}  {label}  {when}  ")
        title = _run_title(run, titles)
        task = _flat(f"[{title}] {run['task']}" if title else run["task"])
        print(f"{prefix}{CYAN}{run['id'][:8]}{RESET}  {label}  "
              f"{DIM}{when}{RESET}  {ui.fit(task, max(20, cols - used))}")
    if hidden:
        print(f"{DIM}이전 기록 {hidden}개는 생략했어요 · "
              f"/agents all 로 모두 보기{RESET}")
    print(f"{DIM}{_AGENTS_HINT}{RESET}")


def _trail_text(line: str) -> str:
    event, _sep, name = str(line).partition(" ")
    if event == "tool_start" and name:
        return f"→ {ui.printable(name)}"
    if event == "tool_end" and name:
        # The trail does not record whether the tool failed, so no ✓.
        return f"← {ui.printable(name)} 끝"
    return _TRAIL_TEXT.get(event) or ui.printable(line)


@command("attach", "실행 중인 에이전트를 따라가고 결과를 봐요.",
         "/attach <실행 ID>")
def _attach(session: Any, arg: str) -> None:
    from . import agentruns, summon
    run = _resolve_run(arg.strip(), "/attach <실행 ID>")
    if run is None:
        return
    id8 = run["id"][:8]
    title = _run_title(run, _agent_titles())
    print(f"{BOLD}{id8}{RESET}  {_run_label(run)}"
          + (f" · {_flat(title)}" if title else ""))
    print(ui.printable_block(run["task"]))
    if run["status"] == "running":
        print(f"{DIM}진행 상황을 따라가는 중이에요. Ctrl-C 를 누르면 여기서만 "
              f"빠져나오고 작업은 계속돼요.{RESET}")
    try:
        final = agentruns.follow(
            run["id"], lambda line: print(f"{DIM}  {_trail_text(line)}{RESET}"))
    except KeyboardInterrupt:
        print(f"\n{DIM}따라가기를 멈췄어요. {id8} 작업은 계속 진행돼요.{RESET}")
        return
    if final is None:
        print(f"{RED}{id8} 실행 기록을 찾을 수 없어요.{RESET}")
        return
    if final["status"] == "running":
        # follow() stops on a running record only once its heartbeat is stale.
        age = agentruns._age_seconds(final.get("last_heartbeat"))
        print(f"{YELLOW}{id8} 작업이 응답하지 않아요 "
              f"(마지막 신호 {ui.duration_ko(age)} 전).{RESET}")
        return
    took = ui.duration_ko(agentruns.elapsed_seconds(final))
    result = str(final.get("result") or "")
    if final["status"] == "error":
        print(f"{RED}작업이 실패했어요.{RESET} {DIM}· {took}{RESET}")
        if result:
            print(f"{DIM}세부: {ui.fit(_flat(result), 200)}{RESET}")
        return
    print(f"{BOLD}{_run_label(final)}{RESET} {DIM}· {took}{RESET}")
    if final["status"] == "done":
        shown = summon.result_text(result)
        print(f"\n{ui.render_markdown(ui.printable_block(shown))}")


@command("send", "실행 중인 에이전트에게 메시지를 보내 방향을 바꿔요.",
         "/send <실행 ID> <메시지>")
def _send(session: Any, arg: str) -> None:
    from . import agentruns
    parts = arg.split(maxsplit=1)
    if len(parts) != 2 or not parts[1].strip():
        print(f"{RED}사용법: /send <실행 ID> <메시지>{RESET}")
        print(f"{DIM}{_RUN_ID_HINT}{RESET}")
        return
    run = _resolve_run(parts[0], "/send <실행 ID> <메시지>")
    if run is None:
        return
    id8 = run["id"][:8]
    # Neither a dead worker nor a finished run drains its inbox; queueing
    # would only claim a delivery that cannot happen.
    if run["status"] == "stale":
        print(f"{RED}{id8} 실행이 응답하지 않아 메시지를 전달할 수 없어요. "
              f"/agents 로 상태를 확인하세요.{RESET}")
        return
    if run["status"] != "running":
        print(f"{RED}{id8} 실행은 이미 끝나서 메시지를 전달할 수 "
              f"없어요. 새 작업은 /summon 으로 시작하세요.{RESET}")
        return
    if not agentruns.append_message(run["id"], parts[1].strip()):
        print(f"{RED}{id8}에 메시지를 보내지 못했어요.{RESET}")
        return
    print(f"{GREEN}{id8}에 메시지를 보냈어요.{RESET} "
          f"{DIM}다음 단계에서 반영돼요.{RESET}")


_ANNOUNCE_PREVIEW_CELLS = 240


def announce_finished_summons() -> None:
    """Print a short completion notice for each finished detached run.

    Every detached run started in this process is announced once, whether
    /summon --bg or the model's spawn_subagent started it, so delegated work
    reports back instead of waiting for the user to remember /attach.
    """
    from . import agentruns, summon
    titles: dict[str, str] | None = None
    for run_id in agentruns.detached_here():
        run = agentruns.get_run(run_id)
        if run is not None and run["status"] == "running":
            continue
        agentruns.forget_detached(run_id)
        if run is None:
            continue
        if titles is None:
            titles = _agent_titles()
        title = _flat(_run_title(run, titles) or "하위 에이전트")
        took = ui.duration_ko(agentruns.elapsed_seconds(run))
        if run["status"] == "done":
            print(f"{GREEN}✓ {title} 작업이 끝났어요{RESET} {DIM}· {took}  "
                  f"/attach {run_id[:8]} 로 결과를 볼 수 있어요.{RESET}")
            # The stored result keeps its head, where the conclusion is.
            preview = ui.fit(_flat(summon.result_text(run.get("result"))),
                             _ANNOUNCE_PREVIEW_CELLS)
            print(f"  {preview}")
        else:
            print(f"{RED}✗ {title} 작업이 실패했어요{RESET} {DIM}· {took}  "
                  f"/attach {run_id[:8]} 로 기록을 확인하세요.{RESET}")


def _print_roster() -> None:
    from . import summon
    roster, rejected = summon.load_roster()
    print(f"{BOLD}소환할 수 있는 에이전트{RESET}")
    for spec in sorted(roster.values(), key=lambda item: item.name):
        mark = f" {DIM}(사용자 정의){RESET}" if spec.source == "user" else ""
        print(f"  {CYAN}{spec.name:<15}{RESET} {_flat(spec.title)}{mark}")
        print(f"  {'':<15} {DIM}{_flat(spec.description)}{RESET}")
    for file_name, reason in sorted(rejected.items()):
        print(f"{YELLOW}  {_flat(file_name)}: 정의가 올바르지 않아 건너뛰었어요 "
              f"(세부: {_flat(reason)}){RESET}")
    print(f"{DIM}사용법: /summon <에이전트> <할 일>  ·  "
          f"백그라운드: /summon --bg <에이전트> <할 일>{RESET}")


def _print_agent(spec: Any) -> None:
    print(f"{BOLD}{_flat(spec.title)}{RESET} ({spec.name})")
    print(_flat(spec.description))
    print(f"{DIM}도구 그룹: {', '.join(spec.tools)}{RESET}")
    if spec.skills:
        print(f"{DIM}미리 불러오는 스킬: {_flat(', '.join(spec.skills))}{RESET}")
    print(f"{DIM}최대 턴: {spec.max_turns}"
          f"{'  ·  모델: ' + spec.model if spec.model else ''}{RESET}")
    print(f"{DIM}사용법: /summon {spec.name} <할 일>  ·  "
          f"백그라운드: /summon --bg {spec.name} <할 일>{RESET}")


def summon_context(ctx: Any, emit: Any) -> Any:
    """``ctx`` for a user-started summon, with its own progress sink.

    The session's sink is never handed over: the workspace one refuses
    events outside its own command, which failed every foreground /summon in
    ``birkin chat`` and stranded its run record and tree-budget lease. The
    tree budget and abort stay the session's shared objects.
    """
    if is_dataclass(ctx) and not isinstance(ctx, type):
        return replace(ctx, emit=emit)
    return ctx


def summon_budget_refusal(cfg: dict[str, Any]) -> str:
    """Why a summon was refused for the token budget, from typed usage."""
    from . import budget
    st = budget.status(cfg)
    check = "사용량은 /status 나 터미널의 birkin budget 으로 확인할 수 있어요."
    if st.get("over_daily"):
        return (f"오늘 토큰 한도(사용 {st['used_today']:,} / 한도 "
                f"{st['daily_cap']:,})를 다 써서 지금은 소환할 수 없어요. "
                f"내일 다시 시도하거나 config.json의 budget_tokens_daily를 "
                f"늘리세요. {check}")
    if st.get("over_monthly"):
        return (f"이번 달 토큰 한도(사용 {st['used_month']:,} / 한도 "
                f"{st['monthly_cap']:,})를 다 써서 지금은 소환할 수 없어요. "
                f"다음 달에 다시 시도하거나 config.json의 "
                f"budget_tokens_monthly를 늘리세요. {check}")
    return f"토큰 한도를 다 써서 지금은 소환할 수 없어요. {check}"


def summon_failure_text(exc: Exception, spec: Any, cfg: dict[str, Any], *,
                        runs_at: str = "/agents 에서") -> tuple[str, str]:
    """A Korean explanation and an optional detail line for a failed summon.

    ``runs_at`` says where the run list lives for this surface.
    """
    from . import budget, summon
    if isinstance(exc, summon.SummonBudgetExceeded):
        return summon_budget_refusal(cfg), ""
    if isinstance(exc, budget.TreeBudgetExceeded):
        # Refused before a run existed, so there is no record to look up.
        return ("지금은 동시에 돌릴 수 있는 에이전트 수나 이번 작업의 위임 "
                f"한도를 넘었어요. {runs_at} 진행 중인 작업을 확인하고 끝난 뒤 "
                "다시 시도하세요.", _flat(exc))
    return (f"{_flat(spec.title)} 작업을 끝내지 못했어요. {runs_at} 실행 "
            "기록을 확인하세요.",
            ui.fit(_flat(f"{type(exc).__name__}: {exc}"), 200))


class SummonProgress:
    """Progress for one user-started summon, fed through the run's ``emit``.

    It prints the start line once the run is registered (so a refused summon
    never claims it started), one line per child tool call, and keeps a
    spinner with the elapsed time between them. ``stream=None`` writes to the
    current stdout, styled; another stream gets plain lines. Used as a
    context manager around the summon, so the spinner always stops.

    The child's tools share this sink: research_run's moirai workers and a
    nested subagent emit their own ``subagent.*`` events, from pool threads.
    So only the first ``subagent.start`` that carries a run id is this run's
    (moirai's carry none), and a lock serializes the spinner and the lines.
    """

    def __init__(self, spec: Any, *, stream: Any = None,
                 spinner: bool = True):
        self._title = _flat(spec.title)
        self._name = spec.name
        self._stream = stream
        self._dim, self._reset = (DIM, RESET) if stream is None else ("", "")
        self._use_spinner = spinner
        self._spinner: ui.Spinner | None = None
        self._active = False
        self._run_id = ""
        self._lock = threading.Lock()
        self.started_at = time.monotonic()

    def _spin(self, on: bool) -> None:
        # Callers hold self._lock.
        if self._spinner is not None:
            self._spinner.stop()
            self._spinner = None
        if on and self._use_spinner and self._active:
            self._spinner = ui.Spinner(f"{self._title} 작업 중…",
                                       "Ctrl-C 로 중단", since=self.started_at)
            self._spinner.start()

    def __enter__(self) -> "SummonProgress":
        with self._lock:
            self.started_at = time.monotonic()
            self._active = True
            self._spin(True)
        return self

    def __exit__(self, *_exc: object) -> None:
        with self._lock:
            self._active = False
            self._spin(False)

    def emit(self, event: str, payload: dict[str, Any]) -> None:
        name = ui.printable(payload.get("name") or "도구")
        run_id = payload.get("id")
        if event == "subagent.start":
            if not isinstance(run_id, str) or not run_id:
                return
            line = (f"{self._title}({self._name}) 에이전트에게 맡겼어요. "
                    "끝날 때까지 기다려요 · Ctrl-C 로 중단")
        elif event == "subagent.tool_start":
            line = f"  → {name}"
        elif event == "subagent.tool_end" and payload.get("is_error"):
            line = f"  ✗ {name} 실패"
        elif event == "subagent.steer":
            line = "  ↪ 보낸 메시지를 반영했어요"
        else:
            return
        with self._lock:
            if event == "subagent.start":
                if self._run_id:
                    return          # a nested run, not this one
                self._run_id = run_id
            self._spin(False)
            print(f"{self._dim}{line}{self._reset}", file=self._stream,
                  flush=True)
            self._spin(True)

    def done_line(self) -> str:
        took = ui.duration_ko(time.monotonic() - self.started_at)
        green = GREEN if self._stream is None else ""
        return (f"{green}✓ {self._title} 작업을 마쳤어요{self._reset} "
                f"{self._dim}· {took}{self._reset}")


def _split_summon_arg(arg: str) -> tuple[bool, list[str]]:
    """``(background, [agent, task])``: --bg may come first or after the name."""
    background = False
    head, _sep, rest = arg.strip().partition(" ")
    text = arg.strip()
    if head == "--bg":
        background, text = True, rest.strip()
    parts = text.split(maxsplit=1)
    if len(parts) == 2:
        after = parts[1].split(maxsplit=1)
        if after[0] == "--bg":
            background = True
            parts = parts[:1] + after[1:]
    return background, parts


@command("summon", "전문가 에이전트에게 일을 맡겨요.",
         "/summon [--bg] [에이전트] [할 일]")
def _summon(session: Any, arg: str) -> None:
    from . import summon
    background, parts = _split_summon_arg(arg)
    if not parts:
        _print_roster()
        return
    try:
        spec = summon.get_agent(parts[0])
    except summon.AgentDefinitionError as exc:
        name = _flat(exc.name)
        print(f"{RED}'{name}' 에이전트 정의 파일(agents/{name}.md)에 문제가 "
              f"있어 소환할 수 없어요. 파일을 고친 뒤 다시 시도하세요.{RESET}")
        print(f"{DIM}세부: {_flat(exc.reason)}{RESET}")
        return
    except summon.SummonError as exc:
        print(f"{RED}'{ui.fit(_flat(parts[0]), 40)}' 에이전트를 찾을 수 없어요. "
              f"/summon 으로 목록을 확인하세요.{RESET}")
        print(f"{DIM}세부: {_flat(exc)}{RESET}")
        return
    if len(parts) == 1:
        _print_agent(spec)
        return
    ctx = getattr(session, "ctx", None)
    if ctx is None:
        print(f"{RED}이 세션에서는 에이전트를 소환할 수 없어요.{RESET}")
        return
    progress = SummonProgress(spec, spinner=not background)
    run_ctx = summon_context(ctx, None if background else progress.emit)
    abort = getattr(ctx, "abort", None)
    if not background and abort is not None:
        abort.clear()  # a new command: drop a stale Esc from an earlier turn
    try:
        with progress:
            result = summon.summon(spec.name, parts[1], run_ctx,
                                   detach=background)
    except KeyboardInterrupt:
        print(f"\n{YELLOW}소환을 중단했어요.{RESET}")
        return
    except Exception as exc:
        message, detail = summon_failure_text(exc, spec, ctx.cfg)
        print(f"{RED}{message}{RESET}")
        if detail:
            print(f"{DIM}세부: {detail}{RESET}")
        return
    if background:
        run_id = summon.detached_run_id(result)
        print(f"{GREEN}{_flat(spec.title)}({spec.name}) 에이전트에게 맡겼어요 "
              f"— 백그라운드에서 진행해요.{RESET}")
        if run_id:
            print(f"/attach {run_id[:8]} 로 따라가고, "
                  f"/send {run_id[:8]} <메시지> 로 방향을 바꿀 수 있어요. "
                  "끝나면 여기서 알려드릴게요.")
        return
    print(progress.done_line())
    print(ui.render_markdown(ui.printable_block(summon.result_text(result))))


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
        print(f"{RED}/goal 인자를 읽을 수 없어요. 따옴표 짝을 확인해 주세요.{RESET}")
        print(f"{DIM}세부: {exc}{RESET}")
        return
    if not parts:
        print(f"{DIM}사용법: /goal set <목표> [--gate \"검증 명령\"] "
              f"| show | pause | done{RESET}")
        return

    action = parts.pop(0).lower()
    if action == "show":
        status = goals.render_status()
        print(status or f"{DIM}진행 중인 목표가 없어요.{RESET}")
        return
    if action == "pause":
        state = goals.pause()
        print(f"{DIM}목표를 잠시 멈췄어요.{RESET}" if state else
              f"{DIM}진행 중인 목표가 없어요.{RESET}")
        return
    if action == "done":
        state = goals.get_active()
        if state is None:
            print(f"{DIM}진행 중인 목표가 없어요.{RESET}")
            return
        final, outcome = goals.request_completion(state, session.cfg)
        if outcome == "queued":
            print(f"{DIM}검증 명령이 승인을 기다리고 있어요: {state.gate_cmd}{RESET}")
            print(f"{RED}/review 에서 승인한 뒤 /goal done 을 다시 실행하면 "
                  f"결과를 확인해 목표를 마무리해요.{RESET}")
            return
        if outcome == "failed":
            print(f"{RED}검증 명령이 실패해서 목표를 계속 진행 중으로 둘게요.{RESET}")
            tail = str((final.gate_last or {}).get("output_tail") or "").strip()
            if tail:
                print(f"{DIM}{tail[-500:]}{RESET}")
            return
        print(f"{GREEN}목표를 완료했어요: {state.objective}{RESET}")
        return
    if action != "set":
        print(f"{RED}알 수 없는 /goal 동작이에요: {action}{RESET}")
        return

    objective: list[str] = []
    gate: str | None = None
    i = 0
    while i < len(parts):
        part = parts[i]
        if part == "--gate":
            if i + 1 >= len(parts):
                print(f"{RED}--gate 뒤에 검증 명령을 적어 주세요.{RESET}")
                return
            gate = parts[i + 1]
            i += 2
            continue
        if part.startswith("--"):
            print(f"{RED}알 수 없는 /goal 옵션이에요: {part}{RESET}")
            return
        objective.append(part)
        i += 1
    try:
        state = goals.set_goal(" ".join(objective), gate=gate)
    except ValueError:   # the only one set_goal raises here: no objective
        print(f"{RED}목표 내용을 적어 주세요.{RESET}")
        return
    print(f"{GREEN}목표를 정했어요: {state.objective}{RESET}")
    print(goals.render_status())
    if state.gate_cmd:
        print(f"{DIM}/goal done 을 실행하면 검증 명령이 승인 대기열을 거쳐 "
              f"실행돼요.{RESET}")


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
            print(f"{YELLOW}⚠ 'full': 이제 CLI 에이전트가 모든 승인과 샌드박스를 "
                  f"건너뛰어 어떤 명령이든 실행하고 어떤 파일이든 수정할 수 "
                  f"있습니다.{RESET}")
    elif len(sub) == 2 and sub[0] == "unattended-full" and sub[1] in ("on", "off"):
        # Let the UNATTENDED nightly Morpheus run keep cli_access "full" (the
        # reachable gateway is ALWAYS workspace regardless). Default off.
        session.cfg["allow_unattended_full"] = (sub[1] == "on")
        config.save_config(session.cfg)
        if sub[1] == "on":
            print(f"{YELLOW}⚠ unattended-full 켜짐: 야간 Morpheus 실행이 샌드박스와 "
                  f"승인을 건너뛸 수 있습니다 (cli_access 'full'도 필요). "
                  f"게이트웨이는 계속 샌드박스 안에서 실행됩니다.{RESET}")
    elif len(sub) == 2 and sub[0] in ("add", "remove"):
        cat = sub[1]
        if sub[0] == "add" and cat in ("shell", "cron", "worker"):
            print(f"{YELLOW}⚠ '{cat}' 자동 승인을 켜면 야간 루틴이 묻지 않고 "
                  f"실행합니다 (Morpheus 예약 시각의 shell 포함).{RESET}")
        if sub[0] == "add" and cat not in auto:
            auto.append(cat)
        elif sub[0] == "remove" and cat in auto:
            auto.remove(cat)
        session.cfg["auto_approve"] = auto
        config.save_config(session.cfg)
    uf = "on" if session.cfg.get("allow_unattended_full") else "off"
    print(f"{DIM}자동 승인: {', '.join(auto) or '(없음)'} · "
          f"CLI 권한: {session.cfg.get('cli_access', 'workspace')} · "
          f"unattended-full: {uf} "
          f"(/permission access workspace|full · unattended-full on|off){RESET}")


# -- session persistence ---------------------------------------------------

def _save(session: Any, arg: str) -> None:
    name = arg or datetime.now().strftime("%Y%m%d-%H%M%S")
    if transcripts.is_auto(name):
        print(f"{RED}Names starting with '{transcripts.AUTO_PREFIX}' are reserved "
              f"for auto-saved transcripts. Pick another name.{RESET}")
        return
    path = config.session_file(name)
    if path is None:
        print(f"{RED}Session names must be plain file names "
              f"(no path separators or '..').{RESET}")
        return
    path.write_text(json.dumps(session.agent.messages, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    print(f"{DIM}Saved to {path}{RESET}")


def _load(session: Any, arg: str) -> None:
    if not arg:
        print(f"{RED}Give a session name (see /sessions).{RESET}")
        return
    path = config.session_file(arg)
    if path is None or not path.is_file():
        print(f"{RED}No session {arg!r}.{RESET}")
        return
    session.agent.messages = json.loads(path.read_text(encoding="utf-8"))
    print(f"{DIM}Loaded {arg} ({len(session.agent.messages)} messages).{RESET}")


@command("sessions", "List/search conversations; /sessions save|load <name>.",
         "/sessions [query] [--since 30d] [--from telegram] [--model name] "
         "| save [name] | load <name>")
def _sessions(session: Any, arg: str) -> None:
    # Hide reserved auto__* transcripts (auto-saved for memory extraction); they
    # are not meant for manual loading and would flood this list.
    verb, _, rest = arg.strip().partition(" ")
    if verb.lower() == "save":
        _save(session, rest.strip())
        return
    if verb.lower() == "load":
        _load(session, rest.strip())
        return
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

def _gateway_token() -> str:
    """Resolve the capability the local HTTP channel checks: env, then file."""
    import os
    from .gateway.channels.capability_file import load_or_create_token
    env_token = (os.environ.get("BIRKIN_HTTP_TOKEN") or "").strip()
    if env_token:
        return env_token
    try:
        return load_or_create_token()[0]
    except (OSError, RuntimeError):
        return ""


def _gateway_post(cfg: dict, text: str) -> str:
    """Send *text* to the local gateway via HTTP and return the reply."""
    import urllib.error
    import urllib.request
    port = cfg.get("gateway_port", 8788)
    url = f"http://127.0.0.1:{port}/message"
    body = json.dumps({"text": text, "session": "repl"}).encode()
    headers = {"Content-Type": "application/json"}
    token = _gateway_token()
    if token:
        # The channel authenticates before it reads the body, so without this
        # header the gateway answers 401 and the URLError arm below would
        # blame connectivity for what is an authentication failure.
        headers["X-Birkin-Token"] = token
    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data.get("reply", "")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return (
                f"{RED}게이트웨이가 권한 토큰을 거부했습니다 (HTTP {exc.code}). "
                f"같은 계정으로 `birkin gateway`를 다시 시작하거나 "
                f"BIRKIN_HTTP_TOKEN을 맞춰 주세요.{RESET}")
        return f"{RED}게이트웨이 요청이 실패했습니다 (HTTP {exc.code}).{RESET}"
    except urllib.error.URLError as exc:
        return f"{RED}Gateway not reachable ({exc}). Is `birkin gateway` running?{RESET}"


@command("restart", "Restart the gateway; --hard also picks up code changes.",
         "/restart [--hard]")
def _restart(session: Any, arg: str) -> None:
    # The wire strings stay as they are: the gateway matches them against its
    # own synonym table (gateway/core.py), which is a separate contract from
    # this REPL command's name.
    a = arg.strip().lower()
    if a not in ("", "--hard", "hard"):
        print("usage: /restart [--hard]")
        return
    wire = "/hard-restart" if a else "/restart-gateway"
    print(_gateway_post(session.cfg, wire))


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

# -- profile / persona -----------------------------------------------------


def _profile_actions(session: Any):
    mem = getattr(session, "memory", None)
    if mem is not None and hasattr(mem, "profile_actions"):
        return mem.profile_actions()
    from .profile_actions import ProfileActions
    from .rolefiles import ProfileStore
    profile = session.cfg.get("profile", {}) if isinstance(session.cfg, dict) else {}
    limits = profile.get("limits", {}) if isinstance(profile, dict) else {}
    return ProfileActions(ProfileStore(config.birkin_home(), limits),
                          approval_required=bool(profile.get("write_approval", False)))


@command("profile", "Review, approve, migrate, or roll back role-profile writes.",
         "/profile pending|approve <ids>|reject <ids>|migrate|rollback")
def _profile(session: Any, arg: str) -> None:
    parts = shlex.split(arg)
    if not parts:
        print("usage: /profile pending|approve <ids>|reject <ids>|migrate|rollback")
        return
    action = parts[0].lower()
    actions = _profile_actions(session)
    if action == "pending":
        pending = actions.pending()
        if not pending:
            print(f"{DIM}No pending profile proposals.{RESET}")
            return
        for item in pending:
            print(json.dumps(item.payload(), sort_keys=True))
        return
    if action in {"approve", "reject"}:
        ids = parts[1:]
        if not ids:
            print(f"usage: /profile {action} <id> [id ...]")
            return
        receipts = actions.approve(ids) if action == "approve" else actions.reject(ids)
        for item in receipts:
            print(json.dumps(item.payload(), sort_keys=True))
        return
    if action == "migrate":
        from .profile_migration import migrate_legacy_preferences
        report = migrate_legacy_preferences(
            actions.store,
            session.memory.legacy_preferences(),
            archive=session.memory.archive_legacy_preference,
        )
        print(json.dumps(report.__dict__, sort_keys=True))
        return
    if action == "rollback":
        from .profile_migration import rollback_legacy_preferences
        report = rollback_legacy_preferences(
            actions.store,
            restore=session.memory.restore_legacy_preference,
            archived=session.memory.archived_legacy_preference,
        )
        print(json.dumps(report.__dict__, sort_keys=True))
        return
    print("usage: /profile pending|approve <ids>|reject <ids>|migrate|rollback")


@command("persona", "Show birkin's persona, switch preset, or promote mask guidance.",
         "/persona [warm|concise|mentor|direct|path|reset|promote]", aliases=["soul"])
def _persona(session: Any, arg: str) -> None:
    # One command for the whole persona surface: showing it, locating its file,
    # resetting it, and switching presets were three names for one concern.
    from . import persona
    name = arg.strip().lower()
    if name == "path":
        print(persona.soul_path())
        return
    if name == "reset":
        persona.seed_default(force=True)
        print(f"{GREEN}Persona reset to the default warm voice.{RESET}")
        return
    if name == "promote":
        promote = getattr(persona, "promote_guidance", None)
        if not callable(promote):
            print(f"{DIM}/persona promote is unavailable until persona support is loaded.{RESET}")
            return
        try:
            guidance = "\n".join(_profile_actions(session).store.snapshot().documents["mask"].entries)
        except Exception as exc:
            print(f"{RED}Could not read profile/mask.md: {exc}{RESET}")
            return
        promote(guidance)
        print(f"{GREEN}Promoted mask guidance into SOUL.md.{RESET}")
        return
    if not name:
        text = persona.read_soul()
        print(f"Presets: {', '.join(persona.PRESETS)}")
        if not text:
            print(f"{DIM}No SOUL.md set — using the built-in default voice. "
                  f"Create {persona.soul_path()} or run /persona <preset>.{RESET}")
        else:
            print(f"{DIM}{persona.soul_path()}{RESET}\n{text}")
        return
    preset = persona.PRESETS.get(name)
    if not preset:
        print(f"{RED}Unknown preset {name!r}. Choose: "
              f"{', '.join(persona.PRESETS)}, or use path|reset.{RESET}")
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
