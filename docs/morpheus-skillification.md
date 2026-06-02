# Morpheus skillification — design

> Status: **proposed** (awaiting review). Date: 2026-06-02.
> Goal: collapse the brittle dual-path Morpheus runtime into the same
> "thin launcher + skill-as-protocol" pattern as `neurosis` / `odyssey`, so the
> routine runs as a normal agent turn (file writes work) instead of a locked-down
> sandboxed subprocess.

## 0. TL;DR

Morpheus today runs through a bespoke runtime with two divergent paths and a
sandbox that **blocks file writes by design** and **silently downgrades
permissions** — which is why it "doesn't run" and "can't write files". We replace
that with a **thin launcher** that gathers the last 24h, makes the bundled
`morpheus` SKILL.md the single source of the procedure, and runs it as a normal
agent turn with writable access to birkin's home. The launcher branches by who
owns the tool loop (it cannot be literally one function call because the write
target — `~/.birkin/{vault,skills,pending}` — sits *outside* the cwd sandbox, so
each surface needs the right writable-dir wiring), but every branch is thin and
the gnarly machinery (temp MCP config, `--strict-mcp-config`, the
`Read/Glob/Grep` allow-list, the permission clamp) is **deleted**.

## 1. Problem (why the current Morpheus is broken)

Evidence from `birkin/morpheus.py` and `birkin/gateway/core.py`:

1. **File writes are blocked by design.** `_run_claude_morpheus`
   (`morpheus.py:140`) spawns a *separate* sandboxed Claude Code process with
   `--allowedTools "Read,Glob,Grep" + mcp__birkin__*`, `--strict-mcp-config`, and
   `permission_mode="default"`. Any normal `Write`/`Edit` is denied — only the
   birkin MCP tools can persist anything. This is the "파일쓰기권한 막힘" symptom.
2. **Permission clamp fights the user.** `run_once` (`morpheus.py:114`) forces
   `cli_access: full → workspace` unless `allow_unattended_full`; the gateway
   downgrades again (`core.py:116`). After a global permission elevation, Morpheus
   re-locks itself, so writes stay blocked.
3. **Two divergent execution paths.** `_run_claude_morpheus` (sandboxed MCP) vs
   `_run_birkin_morpheus` (own agent loop) need different wiring (temp MCP config,
   strict-mcp-config) and are hard to reason about / easy to break.
4. **Doc/impl split.** `skills/automation/morpheus/SKILL.md` already documents the
   full procedure, but execution lives in Python that duplicates it — a
   consistency hazard.
5. **Auto-run is a separate, easily-missing step.** 04:00 firing needs
   `birkin daemon` (long-running) or `birkin daemon --install` (schtasks
   `birkin-nightly`). If neither is installed, Morpheus never fires.

## 2. Decisions (locked)

| # | Decision | Choice |
|---|----------|--------|
| A | Skillification scope | **Thin launcher + skill execution** (mirror neurosis/odyssey). `claude-cli` reuses a sandbox-stripped `ClaudeStreamSession`; API/OAuth providers go through `build_session`; codex/local best-effort via `build_session`. |
| B | Unattended 04:00 auto-run | **Keep** (daemon / schtasks unchanged). |
| C | claude-cli proposal handling | **Pure file-writing — remove MCP entirely.** SKILL.md documents the on-disk formats; `claude` writes memory/skill/proposal files via normal `Write`. |
| D | Unattended `cli_access` clamp | **Remove.** Morpheus inherits `cfg` as-is (runs at the user's configured access level). |

## 3. Architecture (after)

```
run_once(dry_run):
  cfg     = config.load_config()                 # inherited as-is (decision D — no clamp)
  context = _gather_sessions() + _gather_changed_files(cwd) + activity   # unchanged helpers
  task    = start_prompt(context, dry_run)        # neurosis-style: "run morpheus skill" + context

  provider = cfg["provider"]
  if provider == "claude-cli":
      return _run_claude_cli_morpheus(cfg, task, dry_run)   # thin streaming launcher
  return _run_loop_morpheus(cfg, task, dry_run)             # build_session path
```

The branch is **who owns the tool loop** AND **whether the surface can write to
`~/.birkin` (outside the cwd sandbox)**. Three thin shapes:

### (a) `claude-cli` — primary path (the user's actual provider)

A stripped-down `ClaudeStreamSession` — the *same* class the old code used, with
the sandbox machinery removed:

```
sess = ClaudeStreamSession(
    model=cfg["model"], cli_access=cfg["cli_access"],   # inherited (no downgrade)
    permission_mode="acceptEdits",
    append_system_prompt=<morpheus SKILL.md body>,      # single source of procedure
    add_dirs=[str(config.birkin_home())],               # ← makes ~/.birkin writable, scoped to THIS run
    turn_timeout=900.0)                                  # unattended pass needs headroom
summary = sess.ask(task)                                 # task = gathered 24h context + "run morpheus skill"
```

**Removed vs today:** the temp MCP config, `--strict-mcp-config`, the
`--allowedTools Read,Glob,Grep` allow-list, and the `full→workspace` clamp.
**Added:** `add_dirs=[birkin_home]` so the run can write `vault/skills/pending`
*even at `cli_access: workspace`*. Because this widening is on the dedicated
Morpheus launch only (not the shared `_run_claude` client), **normal/gateway
claude turns do NOT gain `~/.birkin` write access** — no security regression for
the reachable gateway.

### (b) API / OAuth providers (`anthropic` / `openai` / `claude-oauth`) — birkin owns the loop

`session = build_session(cfg)`; hard-restrict the registry to
`{files, web, skills, memory}` + attach the `propose_action` tool; `session.ask(task)`.
No `shell`, no `subagent`. Reversible writes (memory/skills) apply directly (birkin
writes to `~/.birkin` in-process, no sandbox); consequential actions (`cron`/`shell`)
go only through `propose_action` → `approvals.propose()` → the pending queue. This
preserves the v2 "approval-first" guarantee exactly as today.

### (c) `codex-cli` / `local-cli` — best-effort via `build_session`

`build_session(cfg).ask(task)` — the CLI agent runs the skill as a normal turn.
Writes to `~/.birkin` depend on that agent's own sandbox/`cli_access` (codex's
workspace sandbox may not reach the home dir); this matches today's acknowledged
"best-effort on codex" caveat (`morpheus.py:189`) and the v2 doc, which lists a
sandboxed-MCP Codex Morpheus as future work. Not a regression.

### On-disk formats (so the `claude-cli` / CLI paths can write directly)

The bundled SKILL.md soft-guards behavior ("propose, don't execute") and documents
the exact formats so the agent can write:
- **memory** → notes under `~/.birkin/vault/` (Markdown + `[[wikilinks]]`),
- **skills** → `~/.birkin/skills/<name>/SKILL.md`,
- **proposals** → one JSON file per action in `~/.birkin/pending/`:
    ```json
    {"id":"<12-hex>","created":"<iso8601>","category":"cron"|"shell",
     "title":"...","description":"...","payload":{...},
     "origin":"morpheus","status":"pending"}
    ```
    (`payload` for `cron`: `{name,hour,minute,type:"prompt"|"shell",value}`;
    for `shell`: `{command}`.) `birkin review` reads these via
    `store.list_pending()`.

### Honest security note (residual risk of decisions C+D)

In claude-cli mode the "propose, don't execute" and "no destructive actions"
rules are **soft guards** (instructions in the SKILL.md system prompt), not a
hard sandbox. The run inherits `cli_access` (the user's config is `workspace`;
`full` only if they set it) **and** is granted write access to `~/.birkin` via
`add_dirs` so it can persist memory/skills/proposals. So an unattended 04:00 pass
can write anywhere under the cwd + `~/.birkin` (and, if `cli_access: full`,
anywhere). This is the explicitly accepted trade-off (decisions C + D); the
mitigation that matters is keeping this widening **scoped to the Morpheus launch**
so normal/gateway turns are unaffected. Recorded in `DECISIONS.md`; revisitable
via the open question in §7.

## 4. Components

| Unit | Change | Purpose / interface |
|------|--------|---------------------|
| `birkin/morpheus.py` | rewrite | `run_once(dry_run)` is now a thin dispatcher → `_run_claude_cli_morpheus` (stripped `ClaudeStreamSession`: `add_dirs=[birkin_home]`, `append_system_prompt=<SKILL.md body>`, `permission_mode="acceptEdits"`, no MCP/strict/allow-list/clamp) for `provider=="claude-cli"`, else `_run_loop_morpheus` (`build_session`; restrict registry + attach `propose_action` only when `provider not in CLI_PROVIDERS`). Keep `_gather_sessions`, `_gather_changed_files`, `_attach_propose_tool`; add `skill_path()` (locate bundled morpheus SKILL.md, like `neurosis.skill_path`) and `start_prompt(context, dry_run)`. Delete the old `_run_claude_morpheus`, `_run_birkin_morpheus` (folded into `_run_loop_morpheus`), `_MORPHEUS_SYSTEM`, and the giant inline `_MORPHEUS_TASK` (procedure → SKILL.md; keep only a compact context-assembly template). |
| `skills/automation/morpheus/SKILL.md` | update | Single source of procedure. Replace the `mcp__birkin__*` instructions with a provider-aware section: "if you have birkin tools (`memory_write_note`/`create_skill`/`improve_skill`/`propose_action`), use them; otherwise write the documented files directly." Document the pending JSON schema + vault/skill paths. Update the Security-model section to the new asymmetry (no sandboxed subprocess). |
| `birkin/nightly.py` | update | Backwards-compat shim: re-export whatever names survive (`run_once`, `_gather_*`, `_attach_propose_tool`); drop `_MORPHEUS_TASK` alias if renamed/removed. |
| `tests/test_morpheus.py` | update | Keep the gather + propose-tool tests. Rewrite the dual-path routing tests for the new dispatch (`claude-cli` → `_run_claude_cli_morpheus`; everything else → `_run_loop_morpheus`). Remove the two clamp tests (behavior deleted); add a test that `run_once` passes `cfg["cli_access"]` through unchanged. Add: `start_prompt` references the morpheus skill and embeds the 24h context; `_run_loop_morpheus` restricts the registry + attaches `propose_action` for `provider not in CLI_PROVIDERS` and does **not** for codex/local; `_run_claude_cli_morpheus` builds a `ClaudeStreamSession` with `add_dirs` containing `birkin_home` and no `--strict-mcp-config`/allow-list (assert via a fake/captured session). |
| `docs/DECISIONS.md` | append | ADR: Morpheus skillified to the neurosis/odyssey pattern; MCP path removed; clamp removed; security asymmetry + accepted residual risk. |
| `docs/STATUS.md` | update | Reflect the new single-path Morpheus. |
| `docs/v2.md` | update | §8 open question ("Should Morpheus be re-expressed as a headless Odyssey run…") — answered: reuses `build_session` + skill protocol; still merely *reuses* (not merged with) Boulder/Osiris. |
| `README.md` / `README.ko.md` | check | Update any Morpheus description that mentions the sandboxed-MCP run. |

Out of scope (do **not** touch): `mcp_server.py` / `mcp.py` stay — the standalone
birkin MCP server is used by other integrations; we only remove *Morpheus's* use
of it. `scheduler.py` (daemon/schtasks) is unchanged (decision B).

## 5. Data flow

```
sessions (~/.birkin/sessions/*.json) ─┐
changed files (cwd walk, mtime<24h)  ─┼─▶ context ─▶ start_prompt ─▶ build_session.ask
activity ledger (~/.birkin/ledger)   ─┘                                   │
                                                                          ▼
   memory notes (vault) · skills (skills dir) · proposals (pending/) · run record (runs/)
                                                                          │
                                                            birkin review / runs / trace
```

## 6. Error handling

- No backend (no API key / not logged in): `build_session` raises `ConfigError`;
  `run_once` catches it, writes a `morpheus skipped — <reason>` run record, returns
  1 (matches current `test_run_once_skips_cleanly_without_a_backend`).
- Agent/turn failure: caught; `morpheus failed: <exc>` run record; return 1; the
  daemon already wraps `run_once` so a failure never kills the scheduler.
- `--dry-run`: assembles context + prompt, but the kickoff instructs "analyze
  only — write nothing, propose nothing", and `_attach_propose_tool` short-circuits
  in dry-run (unchanged).

## 7. Open questions

- Should claude-cli Morpheus pass a *narrower* `cli_access` than the user's config
  (e.g. force `workspace` even with the clamp removed) to shrink unattended blast
  radius while still allowing vault/skill/pending writes? (Deferred — decision D
  says inherit; revisit if the soft guard proves insufficient.)
- Do we want a tiny `birkin morpheus --once-now` smoke path in CI that runs the
  generic loop against a stub client to e2e the single path? (Nice-to-have.)

## 8. Testing

- Unit: gather helpers (unchanged), `start_prompt` content, registry restriction +
  propose attachment per provider, cli_access inheritance, graceful skip.
- `py_compile` + full `pytest` for the package after the rewrite.
- Post-change full review (CLAUDE.md §7): spaghetti, consistency, security,
  progress — run via parallel reviewers.

## Sources
- `birkin/morpheus.py`, `birkin/runtime.py` (`build_session`), `birkin/neurosis.py`
  & `birkin/odyssey.py` (the pattern), `birkin/approvals.py` & `birkin/store.py`
  (`add_pending` schema), `birkin/tools/__init__.py` (`build_registry` groups),
  `skills/automation/morpheus/SKILL.md` (current procedure).
