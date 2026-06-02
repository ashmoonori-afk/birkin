# Morpheus Skillification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Morpheus's brittle dual-path sandboxed runtime with a thin, skill-driven launcher so the nightly self-improvement pass runs as a normal agent turn that can actually write memory/skills/proposals.

**Architecture:** `run_once` becomes a thin dispatcher. For `provider == "claude-cli"` it runs a sandbox-stripped `ClaudeStreamSession` whose system prompt IS the bundled `morpheus` SKILL.md, granted write access to `~/.birkin` via `add_dirs` (scoped to this run only). For API/OAuth providers it runs `build_session` with a registry restricted to `{files,web,skills,memory}` + a `propose_action` tool (approval-first preserved). For codex/local it runs `build_session` best-effort. The SKILL.md becomes the single source of the procedure; the temp-MCP-config / `--strict-mcp-config` / `Read,Glob,Grep` allow-list / permission clamp are deleted.

**Tech Stack:** Python 3.11+ stdlib-only; pytest; the existing birkin modules (`runtime.build_session`, `claude_session.ClaudeStreamSession`, `tools.build_registry`, `approvals`, `store`, `config`).

**Spec:** `docs/morpheus-skillification.md`

**Conventions:** Run all Python with `py` (the `python` command is the MS Store stub on this machine). Tests: `py -m pytest`. The canonical working tree is `C:\Users\lg\Documents\Claude\Projects\Birkin\birkin` (work on `main`). Do NOT commit unless the user asks (global rule) — the `Commit` steps below are explicit; ask before running them, or batch at the end.

---

## File Structure

| File | Responsibility after this plan |
|------|-------------------------------|
| `birkin/morpheus.py` | Thin dispatcher + gather helpers + `skill_path`/`_skill_system`/`start_prompt` + the two run paths + `_attach_propose_tool`. |
| `birkin/nightly.py` | Backwards-compat re-export shim (only surviving names). |
| `skills/automation/morpheus/SKILL.md` | Single source of the Morpheus procedure + provider-aware tool/file guidance + on-disk formats. |
| `tests/test_morpheus.py` | Gather + propose tests (kept) + new dispatch/inheritance/restriction/system-prompt tests. |
| `docs/DECISIONS.md`, `docs/STATUS.md`, `docs/v2.md`, `README.md`, `README.ko.md` | Documentation alignment. |

Untouched (verify, don't edit): `birkin/scheduler.py`, `birkin/mcp_server.py`, `birkin/mcp.py`.

---

## Task 1: Rewrite the test suite to the new design (RED)

**Files:**
- Test: `tests/test_morpheus.py`

We update tests first so they fail against the current implementation, then make them pass in Task 2. Keep the existing gather tests (lines 22-101 of the current file) and the two propose-tool tests (lines 106-161) and `test_run_once_skips_cleanly_without_a_backend` (92-101) verbatim. Replace the template test and ALL the provider-routing/clamp tests (current lines 164-225).

- [ ] **Step 1: Replace the template + routing + clamp tests**

In `tests/test_morpheus.py`, delete from the `# ---------------- task template` comment (line 164) through end of file (line 225) and replace with:

```python
# ---------------- start_prompt (context assembly) -------------------------

def test_start_prompt_contains_required_sections():
    """The kickoff must keep the three context sections Morpheus relies on and
    tell the agent to run the morpheus skill + finish with a [Morpheus] summary."""
    rendered = morpheus.start_prompt("(sess)", "(files)", "(activity)", dry_run=False)
    assert "Last 24h — conversations" in rendered
    assert "Last 24h — changed files" in rendered
    assert "Recent activity log" in rendered
    assert "morpheus" in rendered.lower()        # references the skill
    assert "[Morpheus]" in rendered              # summary label


def test_start_prompt_dry_run_marks_analyze_only():
    rendered = morpheus.start_prompt("(s)", "(f)", "(a)", dry_run=True)
    assert "DRY RUN" in rendered


# ---------------- skill system prompt -------------------------------------

def test_skill_system_returns_skill_body_or_fallback():
    """_skill_system returns non-empty guidance (the bundled SKILL.md body when
    present, else the fallback) — never empty."""
    text = morpheus._skill_system()
    assert isinstance(text, str) and text.strip()
    # The procedure must mention proposing (not executing) consequential actions.
    assert "propos" in text.lower()


# ---------------- provider routing ----------------------------------------

def test_run_once_routes_claude_cli_to_claude_path(monkeypatch):
    config.save_config({**config.DEFAULT_CONFIG, "provider": "claude-cli"})
    called: list[str] = []
    monkeypatch.setattr(morpheus, "_run_claude_cli_morpheus",
                        lambda *a, **k: called.append("claude") or 0)
    monkeypatch.setattr(morpheus, "_run_loop_morpheus",
                        lambda *a, **k: called.append("loop") or 0)
    morpheus.run_once(dry_run=True)
    assert called == ["claude"]


def test_run_once_routes_codex_to_loop_not_claude(monkeypatch):
    # A user on Codex must NOT have `claude` silently spawned for them.
    config.save_config({**config.DEFAULT_CONFIG, "provider": "codex-cli"})
    called: list[str] = []
    monkeypatch.setattr(morpheus, "_run_claude_cli_morpheus",
                        lambda *a, **k: called.append("claude") or 0)
    monkeypatch.setattr(morpheus, "_run_loop_morpheus",
                        lambda *a, **k: called.append("loop") or 0)
    morpheus.run_once(dry_run=True)
    assert called == ["loop"]


def test_run_once_inherits_cli_access_unchanged(monkeypatch):
    """The clamp is gone: run_once passes cfg through to the run path verbatim,
    including cli_access 'full' (no full->workspace downgrade)."""
    config.save_config({**config.DEFAULT_CONFIG, "provider": "codex-cli",
                        "cli_access": "full"})
    seen: dict = {}
    monkeypatch.setattr(morpheus, "_run_loop_morpheus",
                        lambda cfg, *a, **k: seen.update(cfg) or 0)
    morpheus.run_once(dry_run=True)
    assert seen.get("cli_access") == "full"


# ---------------- loop path: registry restriction + propose ----------------

class _FakeRegistry:
    def __init__(self):
        self.tools = {}
    def register(self, tool):
        self.tools[tool.name] = tool


class _FakeAgent:
    def __init__(self):
        self.registry = _FakeRegistry()


class _FakeSession:
    def __init__(self):
        self.agent = _FakeAgent()
        self.ctx = object()
        self.asked = None
    def ask(self, text):
        self.asked = text
        return "[Morpheus] nothing to learn today."


def test_loop_path_restricts_registry_and_proposes_for_api(monkeypatch):
    """For a non-CLI provider (API/OAuth) the loop path swaps in a restricted
    registry and attaches the propose_action tool."""
    fake = _FakeSession()
    monkeypatch.setattr(morpheus, "build_session", lambda cfg: fake)
    captured = {}
    monkeypatch.setattr(morpheus, "build_registry",
                        lambda ctx, include=None: captured.setdefault("include", include)
                        or _FakeRegistry())
    cfg = {**config.DEFAULT_CONFIG, "provider": "anthropic"}
    rc = morpheus._run_loop_morpheus(cfg, "task", dry_run=False, n_files=0)
    assert rc == 0
    assert captured["include"] == {"files", "web", "skills", "memory"}
    assert "propose_action" in fake.agent.registry.tools


def test_loop_path_skips_restriction_for_codex(monkeypatch):
    """For a CLI provider (codex/local) the loop path does NOT restrict the
    registry or attach propose_action — that agent runs its own tools."""
    fake = _FakeSession()
    monkeypatch.setattr(morpheus, "build_session", lambda cfg: fake)
    monkeypatch.setattr(morpheus, "build_registry",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("build_registry must not be called for codex")))
    cfg = {**config.DEFAULT_CONFIG, "provider": "codex-cli"}
    rc = morpheus._run_loop_morpheus(cfg, "task", dry_run=False, n_files=0)
    assert rc == 0
    assert "propose_action" not in fake.agent.registry.tools


# ---------------- claude-cli path: add_dirs + no sandbox -------------------

def test_claude_cli_path_grants_birkin_home_and_no_lockdown(monkeypatch):
    """The claude-cli path builds a ClaudeStreamSession granted write access to
    ~/.birkin (add_dirs) and WITHOUT the old sandbox flags."""
    captured = {}

    class _FakeStream:
        def __init__(self, **kwargs):
            captured.update(kwargs)
        def ask(self, task):
            captured["task"] = task
            return "[Morpheus] done."
        def close(self):
            captured["closed"] = True

    import birkin.claude_session as cs
    monkeypatch.setattr(cs, "ClaudeStreamSession", _FakeStream)
    cfg = {**config.DEFAULT_CONFIG, "provider": "claude-cli", "cli_access": "workspace"}
    rc = morpheus._run_claude_cli_morpheus(cfg, "task-body", dry_run=False, n_files=0)
    assert rc == 0
    home = str(config.birkin_home())
    assert home in (captured.get("add_dirs") or [])
    # cli_access inherited (not downgraded), no strict-mcp / allow-list extra args
    assert captured.get("cli_access") == "workspace"
    assert "extra_args" not in captured or not captured["extra_args"]
    assert captured.get("append_system_prompt")          # skill body present
    assert captured.get("closed") is True
```

- [ ] **Step 2: Run the updated tests to confirm they fail**

Run: `py -m pytest tests/test_morpheus.py -q`
Expected: FAIL — `AttributeError: module 'birkin.morpheus' has no attribute 'start_prompt'` (and `_skill_system`, `_run_loop_morpheus`, `_run_claude_cli_morpheus`, `build_registry`/`build_session` module attrs). The kept gather/propose/skip tests still pass.

---

## Task 2: Rewrite `birkin/morpheus.py` (GREEN)

**Files:**
- Modify (full rewrite): `birkin/morpheus.py`

- [ ] **Step 1: Replace the entire file with the new implementation**

```python
"""Morpheus — the nightly 04:00 self-improvement routine.

Named after the Greek god of dreams: while you sleep, birkin reviews the last
24 hours of conversation and changed files, then improves tomorrow — it compiles
the Obsidian memory vault and authors/refines skills (auto-applied, reversible),
and PROPOSES consequential actions / cron jobs (queued for approval).

This module is a *thin launcher*: it assembles the last-24h context and runs the
bundled ``morpheus`` skill (``skills/automation/morpheus/SKILL.md``) as a normal
agent turn. There is no bespoke sandbox — the procedure lives in the skill, and
each provider runs it with the right writable-dir wiring:

* ``claude-cli`` — a ``ClaudeStreamSession`` whose system prompt is the skill
  body, granted write access to ``~/.birkin`` via ``--add-dir`` (scoped to this
  run only, so normal/gateway turns are unaffected);
* API / OAuth providers — ``build_session`` with the registry restricted to
  reversible groups plus a ``propose_action`` tool (approval-first preserved);
* ``codex-cli`` / ``local-cli`` — ``build_session`` best-effort (the CLI agent
  runs its own tools; full Codex support is future work, see docs/v2.md).

The legacy name ``nightly`` is preserved as an alias (see :mod:`birkin.nightly`).
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from . import approvals, config, selfimprove, store
from .runtime import ConfigError, build_session
from .tools import build_registry

_EXCLUDE_DIRS = {".git", ".birkin", "node_modules", "__pycache__", ".venv",
                 "venv", "dist", "build", ".ruff_cache"}

_CONTEXT_TEMPLATE = """## Morpheus self-improvement pass ({date})

You are running UNATTENDED. Using the last 24 hours of activity below, improve \
the user's tomorrow. Be concrete and conservative; never do anything destructive.

Run the **morpheus** skill now: if you have a load_skill tool, call \
load_skill('morpheus'); otherwise follow birkin's bundled morpheus skill (its \
procedure is in your system prompt and at skills/automation/morpheus/SKILL.md). \
Do all that apply — update memory, author/refine skills, and PROPOSE \
consequential actions (cron/shell) for approval. Do NOT execute consequential \
actions now; queue them as described in the skill.

{dry}

Finish with a short plain-text summary prefixed **[Morpheus]**: what you \
learned, what you saved (memory/skills), and what you are proposing.

---
## Last 24h — conversations
{sessions}

## Last 24h — changed files
{files}

## Recent activity log
{activity}
"""

_FALLBACK_SYSTEM = (
    "You are birkin's nightly self-improvement routine (Morpheus). You run "
    "UNATTENDED while the user sleeps, so be concrete and conservative and never "
    "do anything destructive. Update the Obsidian memory vault and author/refine "
    "skills (reversible, auto-applied). PROPOSE consequential actions (cron/shell) "
    "for the user's approval — never execute them yourself.")


# -- context gathering (deterministic, unit-tested) ------------------------

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


# -- skill resolution ------------------------------------------------------

def skill_path() -> Optional[Path]:
    """Absolute path to the bundled morpheus SKILL.md, if present."""
    for d in config.bundled_skills_dirs():
        hits = list(d.glob("**/morpheus/SKILL.md"))
        if hits:
            return hits[0]
    return None


def _skill_system() -> str:
    """The morpheus SKILL.md body — the single source of procedure — used as the
    append-system-prompt for the claude-cli path. Falls back to a compact system
    string if the skill file is missing/unreadable."""
    sp = skill_path()
    if sp is None:
        return _FALLBACK_SYSTEM
    try:
        from .skills import frontmatter
        text = sp.read_text(encoding="utf-8", errors="replace")
        _, body = frontmatter.split_frontmatter(text)
        return body.strip() or _FALLBACK_SYSTEM
    except OSError:
        return _FALLBACK_SYSTEM


def start_prompt(sessions: str, files: str, activity: str, dry_run: bool) -> str:
    """Assemble the kickoff the agent receives (context + 'run the morpheus skill')."""
    return _CONTEXT_TEMPLATE.format(
        date=datetime.now().strftime("%Y-%m-%d"),
        dry=("(DRY RUN: only analyze — do not write memory/skills or propose.)"
             if dry_run else ""),
        sessions=sessions, files=files, activity=(activity or "")[:6000])


# -- entry point -----------------------------------------------------------

def run_once(dry_run: bool = False) -> int:
    cfg = config.load_config()                    # inherited as-is (no clamp)
    cwd = Path.cwd()
    sessions_text = _gather_sessions()
    files_text = _gather_changed_files(cwd)
    activity = store.read_recent_activity() or "(empty)"
    task = start_prompt(sessions_text, files_text, activity, dry_run)
    n_files = files_text.count("\n- ") + (1 if files_text.startswith("- ") else 0)

    if cfg.get("provider") == "claude-cli":
        return _run_claude_cli_morpheus(cfg, task, dry_run, n_files)
    return _run_loop_morpheus(cfg, task, dry_run, n_files)


def _run_claude_cli_morpheus(cfg: dict[str, Any], task: str, dry_run: bool,
                             n_files: int) -> int:
    """Skill-driven Claude run. The SKILL.md body is the system prompt; the run is
    granted write access to ~/.birkin (add_dirs) so it can persist memory/skills/
    proposals. No sandbox lockdown — file writes work; cli_access is inherited."""
    from .claude_session import ClaudeStreamSession

    sess = ClaudeStreamSession(
        model=cfg.get("model"),
        cli_access=cfg.get("cli_access", "workspace"),
        permission_mode="acceptEdits",
        append_system_prompt=_skill_system(),
        add_dirs=[str(config.birkin_home())],
        turn_timeout=900.0)
    print("birkin morpheus: analyzing the last 24h… (claude, skill-driven)")
    try:
        summary = sess.ask(task)
    except Exception as exc:
        msg = f"morpheus failed: {exc}"
        print(msg)
        store.save_run("morpheus", msg)
        return 1
    finally:
        sess.close()
    store.save_run("morpheus", summary,
                   {"backend": "claude-cli", "changed_files": n_files,
                    "dry_run": dry_run})
    print("\n=== morpheus summary ===\n" + summary)
    print("\nReview any proposed actions with `birkin review`.")
    return 0


def _run_loop_morpheus(cfg: dict[str, Any], task: str, dry_run: bool,
                       n_files: int) -> int:
    """birkin's own agent loop. For API/OAuth providers (birkin owns the loop) the
    registry is restricted to reversible groups + a propose_action tool so
    consequential actions queue for approval. For codex/local CLI providers the
    agent runs its own tools, so no restriction applies (best-effort)."""
    try:
        session = build_session(cfg)
    except ConfigError as exc:
        msg = f"morpheus skipped — {exc}"
        print(msg)
        store.save_run("morpheus", msg)
        return 1

    proposals: list[dict[str, Any]] = []
    if cfg.get("provider") not in config.CLI_PROVIDERS:
        # SECURITY: birkin owns this tool loop, so hard-restrict it — no shell,
        # no subagent. Consequential actions go only through propose_action.
        session.agent.registry = build_registry(
            session.ctx, include={"files", "web", "skills", "memory"})
        _attach_propose_tool(session, cfg, proposals, dry_run)

    print("birkin morpheus: analyzing the last 24h…")
    try:
        summary = session.ask(task)
    except Exception as exc:
        msg = f"morpheus failed: {exc}"
        print(msg)
        store.save_run("morpheus", msg)
        return 1

    store.save_run("morpheus", summary,
                   {"proposals": proposals, "changed_files": n_files,
                    "dry_run": dry_run})
    print("\n=== morpheus summary ===\n" + summary)
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
            payload=inp.get("payload", {}) or {}, cfg=cfg, origin="morpheus")
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
```

Note: `build_session` and `build_registry` are imported at module top so the Task 1 tests can `monkeypatch.setattr(morpheus, "build_session", ...)` / `"build_registry"`.

- [ ] **Step 2: Run the morpheus tests to verify they pass**

Run: `py -m pytest tests/test_morpheus.py -q`
Expected: PASS (all kept + new tests). If `test_claude_cli_path_*` fails on import, confirm the patch target is `birkin.claude_session.ClaudeStreamSession` (the function imports it lazily from that module, so patching the module attribute works).

- [ ] **Step 3: Compile-check the module**

Run: `py -m py_compile birkin/morpheus.py`
Expected: no output (success).

---

## Task 3: Update the `nightly` backwards-compat shim

**Files:**
- Modify: `birkin/nightly.py`

The current shim imports `_MORPHEUS_TASK as _NIGHTLY_TASK`, which no longer exists.

- [ ] **Step 1: Confirm nothing imports the removed alias**

Run: `py -c "import subprocess,sys; sys.exit(0)"` then search:
Run: `rg "_NIGHTLY_TASK|_MORPHEUS_TASK|_run_claude_morpheus|_run_birkin_morpheus" -n`
Expected: only matches inside `docs/` and this plan — NOT in `birkin/` or `tests/`. If a test references them, update that test to the new names.

- [ ] **Step 2: Replace the shim body**

```python
"""Backwards-compatibility shim — the routine was renamed to **Morpheus**.

This module re-exports the stable surface of :mod:`birkin.morpheus` so any
external import path that still says ``birkin.nightly`` keeps working.
"""

from __future__ import annotations

from .morpheus import (   # noqa: F401  (re-exports for backwards compatibility)
    _attach_propose_tool,
    _gather_changed_files,
    _gather_sessions,
    run_once,
    start_prompt,
)
```

- [ ] **Step 3: Verify the shim imports**

Run: `py -c "import birkin.nightly as n; print(n.run_once, n.start_prompt)"`
Expected: prints two function reprs, no ImportError.

- [ ] **Step 4: Commit (ask first per global rule)**

```bash
git add birkin/morpheus.py birkin/nightly.py tests/test_morpheus.py
git commit -F - <<'MSG'
refactor: skillify Morpheus into a thin launcher

Collapse the dual-path sandboxed runtime into a thin dispatcher. claude-cli runs
the morpheus SKILL.md as a normal turn with ~/.birkin granted via add_dirs;
API/OAuth providers use build_session with a restricted registry + propose_action;
codex/local are best-effort. Removes the temp MCP config, strict-mcp-config, the
Read/Glob/Grep allow-list, and the cli_access clamp — so file writes work.
MSG
```

---

## Task 4: Make the SKILL.md the single source of procedure

**Files:**
- Modify: `skills/automation/morpheus/SKILL.md`

Rewrite two sections so the skill is accurate for BOTH tool surfaces (birkin native tools vs plain file writes) and no longer references the deleted MCP sandbox.

- [ ] **Step 1: Replace the "Procedure" intro paragraph**

Find (current lines 56-60):

```markdown
Do all that apply, in this order, using the birkin tools provided over MCP
(`mcp__birkin__memory_write_note`, `…create_skill`, `…improve_skill`,
`…propose_action`, plus `…memory_search` / `…memory_get_note` / `…memory_link`).
Analyze the workspace with **Read / Glob / Grep only** — there is **no shell**.
```

Replace with:

```markdown
Do all that apply, in this order. **Use whichever tool surface you have:**

- **If you have birkin's tools** (`memory_write_note`, `memory_search`,
  `memory_get_note`, `memory_link`, `create_skill`, `improve_skill`,
  `propose_action`) — the API/OAuth path — use them directly.
- **Otherwise** (the claude-cli / codex file-only path) — write the documented
  files directly with your normal file tools, to the paths in **On-disk formats**
  below. You have been granted write access to `~/.birkin` for this run.

Analyze the workspace by reading it; do **not** run destructive commands.
```

- [ ] **Step 2: Replace the "Security model" section**

Find the whole section (current lines 97-109, starting `## Security model (why this is safe to run unattended)` through the bullet ending `risk-tiered for \`birkin review\`.`) and replace with:

```markdown
## Security model (why this is safe to run unattended)

- **Single source of procedure.** This skill *is* the routine — there is no
  separate sandboxed subprocess. A thin launcher (`birkin/morpheus.py`) assembles
  the last-24h context and runs this skill as a normal agent turn.
- **API / OAuth path (birkin owns the tool loop).** The tool registry is
  hard-restricted to `{files, web, skills, memory}` plus a `propose_action` tool —
  **no shell, no subagent**. Reversible writes (memory/skills) apply directly;
  consequential actions (`cron`/`shell`) go only through `propose_action` →
  the `approvals` queue.
- **claude-cli / codex path (the CLI agent owns the tool loop).** The routine
  runs at the user's `cli_access`, granted write access to `~/.birkin` for this
  run only (so normal/gateway turns are unaffected). Here the "propose, don't
  execute" rule is a **soft guard**: never run a `cron`/`shell` action yourself —
  write it to the approval queue (see **On-disk formats**) and stop.
- In all paths, memory + skills are reversible local files; cron/shell are queued
  and risk-tiered for `birkin review`.

## On-disk formats (file-only path)

When you don't have birkin's tools, persist results as plain files:

- **Memory** → a Markdown note under `~/.birkin/vault/` (use `[[wikilinks]]`;
  update an existing note instead of duplicating).
- **Skill** → `~/.birkin/skills/<name>/SKILL.md` (valid frontmatter: `name`,
  `description`, `version`, `license`; a clear "When to Use").
- **Proposal** → one JSON file per action at `~/.birkin/pending/<id>.json`, where
  `<id>` is a fresh 12-hex string and the same value as the `id` field:

  ```json
  {"id": "<12-hex>", "created": "<ISO-8601 UTC>", "category": "cron",
   "title": "...", "description": "...",
   "payload": {"name": "...", "hour": 8, "minute": 0,
               "type": "prompt", "value": "..."},
   "origin": "morpheus", "status": "pending"}
  ```

  For a `shell` proposal use `"category": "shell"` and
  `"payload": {"command": "..."}`. `birkin review` lists and approves these.
```

- [ ] **Step 3: Update the entrypoint frontmatter note (optional accuracy)**

In the frontmatter `metadata.birkin.entrypoint` (line 10), no change is required, but verify the text still reads true (`birkin morpheus` / `birkin daemon --install`). Leave as-is.

- [ ] **Step 4: Confirm no stale MCP references remain**

Run: `rg "mcp__birkin__|strict-mcp-config|allowedTools|Read / Glob / Grep only" skills/automation/morpheus/SKILL.md`
Expected: no matches.

- [ ] **Step 5: Validate the skill frontmatter still parses**

Run: `py -c "from birkin.skills import loader, config" 2>$null; py -c "from birkin.skills.loader import discover; from birkin import config; ds=discover([(d,'bundled') for d in config.bundled_skills_dirs()]); print('morpheus' in ds, ds['morpheus'].description[:40])"`
Expected: `True ...` (the skill still discovers and its description loads).

---

## Task 5: Documentation alignment

**Files:**
- Modify: `docs/DECISIONS.md` (append), `docs/STATUS.md`, `docs/v2.md`, `README.md`, `README.ko.md`

- [ ] **Step 1: Append an ADR to `docs/DECISIONS.md`**

Append at the end of the file (use the next ADR number — check the last `## ADR-NNN` heading and increment):

```markdown
## ADR-0NN: Morpheus skillified into a thin launcher

**Date:** 2026-06-02
**Status:** Accepted

**Context.** The Morpheus nightly routine ran through a bespoke dual-path runtime.
The `claude-cli` path spawned a sandboxed Claude subprocess with
`--allowedTools Read,Glob,Grep` + `mcp__birkin__*`, `--strict-mcp-config`, and a
`cli_access full→workspace` clamp — which blocked all file writes and made the
routine effectively unable to persist anything, while duplicating the procedure
already documented in `skills/automation/morpheus/SKILL.md`.

**Decision.** Collapse the runtime into a thin launcher that runs the bundled
`morpheus` skill as a normal agent turn (mirrors `neurosis`/`odyssey`):
- `claude-cli` → a sandbox-stripped `ClaudeStreamSession` whose system prompt is
  the SKILL.md body, granted `~/.birkin` write access via `add_dirs` scoped to the
  run; `cli_access` inherited (no clamp).
- API/OAuth → `build_session` with the registry restricted to
  `{files,web,skills,memory}` + a `propose_action` tool (approval-first preserved).
- `codex-cli`/`local-cli` → `build_session` best-effort.
Deleted: the temp MCP config, `--strict-mcp-config`, the `Read,Glob,Grep`
allow-list, and the `cli_access` clamp. Proposals on the file-only path are
written directly to `~/.birkin/pending/<id>.json`.

**Consequences.** File writes work. The SKILL.md is the single source of the
procedure. Trade-off: on the `claude-cli`/codex path "propose, don't execute" is a
**soft guard** (instruction), not a hard sandbox, and the unattended run can write
under the cwd + `~/.birkin` at the user's `cli_access`. The widening is scoped to
the Morpheus launch, so normal/gateway turns are unaffected.
```

- [ ] **Step 2: Update `docs/STATUS.md`**

Run: `rg -n "[Mm]orpheus" docs/STATUS.md` and update any line describing the old sandboxed-MCP run so it reads, e.g.: "Morpheus: thin skill-driven launcher (claude-cli runs the morpheus SKILL.md with ~/.birkin granted; API/OAuth via build_session + propose_action)." Keep the file's existing style/format.

- [ ] **Step 3: Resolve the open question in `docs/v2.md`**

In `docs/v2.md` §8, replace the bullet:

```markdown
- Should Morpheus (nightly) be re-expressed as a headless Odyssey run, or stay
  separate and merely *reuse* Boulder/Osiris? (Lean: reuse, don't merge.)
```

with:

```markdown
- ~~Should Morpheus (nightly) be re-expressed as a headless Odyssey run…~~
  **Resolved (2026-06-02):** Morpheus is a thin skill-driven launcher (same
  pattern as Neurosis/Odyssey) via `build_session` / a sandbox-stripped
  `ClaudeStreamSession`; it merely *reuses* primitives, not merged with Odyssey.
  See `docs/morpheus-skillification.md`.
```

- [ ] **Step 4: Update READMEs if they describe the sandboxed run**

Run: `rg -n "morpheus|Morpheus|strict-mcp|allowedTools|sandboxed" README.md README.ko.md`
For any line that describes Morpheus as a "sandboxed Claude + birkin MCP" run, change it to describe the skill-driven launcher. If the READMEs only mention `birkin morpheus` as a command (no sandbox detail), no change is needed — note that in the commit.

- [ ] **Step 5: Commit docs (ask first per global rule)**

```bash
git add docs/ README.md README.ko.md skills/automation/morpheus/SKILL.md
git commit -m "docs: align Morpheus docs + SKILL.md with the skillified launcher"
```

---

## Task 6: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Compile all changed modules**

Run: `py -m py_compile birkin/morpheus.py birkin/nightly.py`
Expected: success.

- [ ] **Step 2: Run the full test suite**

Run: `py -m pytest -q`
Expected: all pass. If unrelated pre-existing failures appear, note them but do not fix in this plan (out of scope).

- [ ] **Step 3: Smoke the dispatcher without a live model (dry-run, codex stub)**

Run: `py -c "from birkin import config, morpheus; config.save_config({**config.DEFAULT_CONFIG,'provider':'codex-cli'}); print('dispatch ok')"`
Expected: prints `dispatch ok` (import + config path works; we do not invoke a live model here).

- [ ] **Step 4: Confirm the daemon still wires to `run_once` (decision B — auto-run kept)**

Run: `rg -n "from .morpheus import run_once|run_once\(\)" birkin/scheduler.py`
Expected: the scheduler still imports and calls `run_once()` (unchanged).

---

## Task 7: Post-change review (CLAUDE.md §7)

**Files:** none (review only)

- [ ] **Step 1: Run parallel reviewers**

Dispatch reviewers in parallel over the diff (spaghetti/consistency, security, plan-progress):
- `security-reviewer` — focus: the claude-cli `add_dirs=[birkin_home]` widening is scoped to the Morpheus run only (not the shared `_run_claude` client); the propose/approval path is intact for API/OAuth; no secret leakage in run records.
- `code-reviewer` — focus: dead code removed (no orphan `_run_claude_morpheus`/`_MORPHEUS_TASK`/`_MORPHEUS_SYSTEM` references), imports clean, files focused, error handling preserved.
- consistency check — SKILL.md ↔ `morpheus.py` ↔ spec ↔ DECISIONS agree.

- [ ] **Step 2: Address CRITICAL/HIGH findings, then re-run `py -m pytest -q`**

Expected: green; findings resolved or explicitly deferred with rationale.

---

## Self-Review (author checklist — completed)

- **Spec coverage:** decisions A–D → Tasks 2 (dispatch, claude-cli add_dirs, no clamp, loop restriction), 4 (SKILL.md single source + on-disk formats), 5 (docs); auto-run kept → Task 6 Step 4; gather helpers preserved → Task 2; tests rewritten → Task 1. ✓
- **Placeholder scan:** README step is a grep-and-edit with an explicit decision rule (no blind placeholder); all code steps show full code. ✓
- **Type consistency:** function names used across tasks match (`start_prompt`, `_skill_system`, `skill_path`, `_run_claude_cli_morpheus`, `_run_loop_morpheus`, `_attach_propose_tool`); test patch targets (`morpheus.build_session`, `morpheus.build_registry`, `birkin.claude_session.ClaudeStreamSession`) match the imports in Task 2. ✓
```
