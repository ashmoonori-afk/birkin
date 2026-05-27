"""The nightly 04:00 self-improvement routine.

It reviews the last 24h of conversation and changed files, then:
1. compiles the Obsidian memory vault (entities, facts, links)  — applied directly,
2. authors/refines skills for repeatable procedures              — applied directly,
3. PROPOSES convenience actions and cron jobs                    — queued for approval.

Safe changes (memory, skills) are auto-applied per the permission policy;
consequential ones (cron, shell) go through :mod:`approvals`.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import approvals, config, selfimprove, store
from .runtime import ConfigError, build_session

_EXCLUDE_DIRS = {".git", ".birkin", "node_modules", "__pycache__", ".venv",
                 "venv", "dist", "build", ".ruff_cache"}

_NIGHTLY_TASK = """## Nightly self-improvement pass ({date})

You are running unattended. Using the last 24 hours of activity below, improve \
the user's tomorrow. Be concrete and conservative.

Do all that apply:
1. **Memory** — capture durable entities, facts, decisions, and relationships in \
the Obsidian vault with memory_write_note, linking related notes ([[wikilinks]]). \
Update existing notes rather than duplicating.
2. **Skills** — if you observed a repeatable procedure, create_skill (or \
improve_skill). Keep them generalizable.
3. **Proposals** — for anything that would help tomorrow but changes the world \
(scheduled digests, prefetching, reminders, automations), call propose_action. \
These are NOT executed now; the user approves them later. Do not propose risky \
or destructive actions.

Finish with a short plain-text summary: what you learned, what you saved, and \
what you are proposing.

{dry}

---
## Last 24h — conversations
{sessions}

## Last 24h — changed files
{files}

## Recent activity log
{activity}
"""


def _gather_sessions(hours: float = 24.0) -> str:
    import json
    cutoff = time.time() - hours * 3600
    chunks: list[str] = []
    for f in sorted(config.sessions_dir().glob("*.json")):
        try:
            if f.stat().st_mtime < cutoff:
                continue
            messages = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        chunks.append(f"### session {f.stem}\n"
                      + selfimprove.transcript_from_messages(messages))
    return "\n\n".join(chunks)[:20000] or "(no saved conversations in the last 24h)"


def _gather_changed_files(root: Path, hours: float = 24.0, limit: int = 60) -> str:
    cutoff = time.time() - hours * 3600
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDE_DIRS
                       and not d.startswith(".")]
        for name in filenames:
            p = Path(dirpath) / name
            try:
                if p.stat().st_mtime >= cutoff:
                    found.append(str(p.relative_to(root)))
            except OSError:
                continue
            if len(found) >= limit:
                break
        if len(found) >= limit:
            break
    return "\n".join(f"- {f}" for f in found) or "(no files changed in the last 24h)"


def run_once(dry_run: bool = False) -> int:
    cfg = config.load_config()
    try:
        session = build_session(cfg)
    except ConfigError as exc:
        msg = f"nightly skipped — {exc}"
        print(msg)
        store.save_run("nightly", msg)
        return 1

    cwd = session.ctx.cwd
    sessions_text = _gather_sessions()
    files_text = _gather_changed_files(cwd)
    activity = store.read_recent_activity() or "(empty)"

    proposals: list[dict[str, Any]] = []
    _attach_propose_tool(session, cfg, proposals, dry_run)

    task = _NIGHTLY_TASK.format(
        date=datetime.now().strftime("%Y-%m-%d"),
        dry=("(DRY RUN: do not call propose_action.)" if dry_run else ""),
        sessions=sessions_text, files=files_text, activity=activity[:6000])

    print("birkin nightly: analyzing the last 24h…")
    try:
        summary = session.ask(task)
    except Exception as exc:
        msg = f"nightly failed: {exc}"
        print(msg)
        store.save_run("nightly", msg)
        return 1

    details = {"proposals": proposals,
               "changed_files": files_text.count("\n- ") + (1 if "- " in files_text else 0)}
    store.save_run("nightly", summary, details)
    print("\n=== nightly summary ===\n" + summary)
    if proposals:
        print(f"\n{len(proposals)} proposal(s) queued. Run `birkin review` to act on them.")
    return 0


def _attach_propose_tool(session, cfg: dict[str, Any],
                         proposals: list[dict[str, Any]], dry_run: bool) -> None:
    from .tools import Tool, ToolContext, ToolResult

    def propose_action(inp: dict[str, Any], ctx: ToolContext) -> ToolResult:
        category = inp.get("category", "cron")
        title = inp.get("title", "(untitled)")
        if dry_run:
            return ToolResult(f"(dry-run) would propose [{category}] {title}")
        status = approvals.propose(
            category=category, title=title,
            description=inp.get("description", ""),
            payload=inp.get("payload", {}) or {}, cfg=cfg, origin="nightly")
        proposals.append({"category": category, "title": title, **status})
        if status.get("auto"):
            return ToolResult(f"Applied [{category}] {title}: {status.get('result')}")
        return ToolResult(f"Queued for approval [{category}] {title} "
                          f"(id {status.get('id')}).")

    session.agent.registry.register(Tool(
        name="propose_action",
        description="Propose a convenience action or cron job for tomorrow. It "
                    "is queued for the user's approval (not executed now). Use "
                    "category 'cron' with payload {name, hour, minute, type "
                    "('prompt'|'shell'), value}, or 'shell' with payload "
                    "{command}.",
        input_schema={"type": "object", "properties": {
            "category": {"type": "string", "enum": ["cron", "shell"]},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "payload": {"type": "object"}},
            "required": ["category", "title"]},
        fn=propose_action))
