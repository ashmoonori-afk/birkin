# birkin — Build Status

> Snapshot: 2026-06-02 · **500 tests** · 53 skills. Newest: **`birkin compare`**
> (blind A/B two-model compare, odysseus-style) + **deep-research → report file**
> (writes `~/.birkin/research/<slug>.md`) + **unattended-full opt-in** so the
> nightly Morpheus run *can* keep `cli_access: full` when explicitly enabled
> (`/permission unattended-full on`; gateway stays sandboxed) — see ADR-036.
>
> v0.2 (hardening; H2–H6 complete) + gateway speed
> + Neurosis + autosave→memory + session-review hardening (ADR-032)
>
> **v2 design (proposed, not built):** [`docs/v2.md`](./v2.md) — borrowing
> HIGH+MEDIUM ideas from oh-my-openagent: always-on infra (Model Router, Hashline
> edits, IntentGate, Prompt-Gate, scoped skills) + an on-demand **Odyssey** goal-
> completion cycle (Neurosis → Hyperplan critique → Boulder state → **Osiris**
> verify). Odyssey is a skill (`skills/automation/odyssey`), so the heavy cycle
> runs only on a complex goal, never every turn. **53 bundled skills** (incl.
`creative/codex-image-gen` — free gpt-image-2 via Codex OAuth; and
`quality/model-compare` — blind A/B model compare).
>
> **493 tests** pass offline (no API key). Newest: **Esc / typing interrupts the
> in-flight REPL turn** (ADR-035) — cooperative `Session.abort` threaded through
> `agent.run`/`LLMClient` (Anthropic stream stops; CLI subprocess killed via the
> new `_run_cli_capture`) + a TTY-only interrupt listener (`abortkey.py`): Esc
> cancels, or type a new message + Enter to interrupt AND send it next. Also: **all
> v2 components built**
> (code-reviewed: 1 HIGH + 3 MEDIUM fixed — boulder zombie/evidence-gate, router
> free-tier guarantee + token routing).
> (docs/v2.md) — #1 Model Router (`router.py`), #2 Hashline edits, #3 Osiris
> verifier (`verify.py`), #4 IntentGate (`intent.py`), #5 Boulder (`boulder.py`),
> #6 Hyperplan (`critique.py`), #7 Prompt-Gate (`promptgate.py`, runtime+gateway
> routed through it + static audit), #8 per-skill scoped perms, + Odyssey wiring
> (`odyssey.py`). Infra (#7,#2) wired live; the rest ship as tested primitives +
> the Odyssey skill protocol (opt-in; hot path untouched). Also: **Codex-backend compatibility**
> (ADR-034) — morpheus no longer spawns `claude` for codex users (routes generic),
> unattended runs downgrade `cli_access:full`→`workspace`, and gateway `/models` is
> provider-aware (codex model ids pass through). Persistent warm gateway stays
> claude-cli-only by design (codex `exec` is one-shot). Also: **Telegram replies render
> Markdown** — GFM → Telegram HTML (`parse_mode="HTML"`) via
> `gateway/channels/tg_format.py`, with tables → aligned (CJK-aware) monospace
> `<pre>`, 4096-safe splitting, and a plain-text fallback if Telegram rejects a
> chunk (ADR-033). Earlier this session:
> of the free+fast gateway / Neurosis / autosave work — **0 CRITICAL**, 8 HIGH
> fixed, then a MEDIUM/LOW follow-up pass (19-agent triage) fixed **16 more** real
> findings: atomic `save_config`, transcript mask-before-truncate, cron clock
> clamp, unique `_write_json` temp, collision-resistant Neurosis slug + no skill-
> path leak + `BIRKIN_HOME`-aware hints, `/neurosis` seed under the lock, atomic
> `write_soul`, dry-run packet fidelity, byte-accurate MCP line guard. 6 false-
> positives + 8 LOW wont-fix dismissed. See ADR-032.

A concise, kept-current summary of what exists and how to run it. For the full
design see [DESIGN.md](./DESIGN.md); for rationale see [DECISIONS.md](./DECISIONS.md).
Improvement roadmap: [IMPROVEMENT-PLAN.md](./IMPROVEMENT-PLAN.md). Positioning
against the upstream catalogs: [COMPARISON.md](./COMPARISON.md).

## Gateway: free + fast (2026-05-29) — see ADR-026

Goal: lighter than hermes, faster, while staying **free** (Claude subscription
OAuth, no paid API key).

- **21s → ~3s warm replies, free.** Two changes:
  1. Removed the broken global `clawd-on-desk` hooks (per-event `wmic` tax):
     `claude -p` 21s → ~8s. (Backup: `~/.claude/settings.json.bak-clawd-hooks`.)
  2. `birkin/claude_session.py` — one **warm** `claude` stream-json process per
     conversation (cold-start paid once; warm turns ~model-time ~3s, context
     kept). Wired into the gateway via `gateway_persistent` (default true).
- Gateway chat commands: `/new` (fresh conversation) and **`/restart-gateway`**
  (alias `/restart`) — soft-restart in place: reload config/persona/memory/skills
  and drop warm sessions, no process kill (code changes still need a real restart).
  **`/models [name]`** lists or selects the gateway model and **auto hard-restarts**
  to apply it (the gateway's model is fixed at process start); REPL `/models [name]`
  selects live (no restart).
- **Direct-API OAuth is parked, not used:** Anthropic meters third-party OAuth
  API use as paid `extra_usage` (≠ free Claude Code billing). `birkin/oauth.py`
  is retained only for the read-only usage check. See ADR-026.
- Tests: 287 pass (8 new for `claude_session`). Verified live (cold ~8s, warm ~3s).

## Neurosis — deep interview (2026-06-01) — see ADR-031

- `/neurosis [--quick|--standard|--deep] <idea>` (REPL + Telegram gateway) and
  `birkin neurosis "<idea>"` (CLI) run a **Socratic, ambiguity-gated** interview:
  one question at a time targeting the weakest clarity dimension, ambiguity =
  `1 − Σ(dim×weight)`, won't proceed until `≤ threshold`. Topology + ontology +
  challenge modes (R4/R6/R8) + resumable state + crystallized spec.
- Ported from gajae-code's deep-interview. Skill (`skills/planning/neurosis/SKILL.md`,
  Korean interview / English spec) + thin runtime (`birkin/neurosis.py`). Spec →
  `~/.birkin/specs/neurosis-{slug}.md`; approve → birkin executes / save to memory
  for Morpheus / refine. Re-seeding the same idea resumes (no clobber).
- **Auto-trigger** (`neurosis_auto`, default true): birkin proactively runs/offers
  the interview for complex/vague work/project requests (and acts directly on
  specific ones) — wired into the gateway + REPL system prompts. 386 tests pass.

## Auto-save transcripts → memory (2026-06-01) — see ADR-030

- `birkin/transcripts.py` auto-saves every (user, assistant) turn — gateway
  (persistent + non-persistent) and REPL — to `sessions_dir()` as reserved
  `auto__*.json` in the canonical format the nightly **Morpheus** routine already
  consumes. So memory is now extracted from real conversations automatically
  (nightly); no manual `/save` needed. Hidden from `/sessions`.
- **Trust-gated:** open Telegram bots (no `allowed_chat_ids`) are NOT persisted/
  memorized (anti memory-poisoning). Secret redaction + per-message cap +
  retention; `0o600`. Opt-out: `autosave_transcripts=false`.
- On-demand `/new`/idle extraction deferred to v2 (would reuse
  `selfimprove.reflect_and_learn`). 371 tests pass.

## Security hardening (2026-05-29) — see ADR-029

- **cron→shell laundering closed**: an auto-approved `cron` can't auto-run a
  shell payload unless `shell` is also auto-approved (else queued for review).
- **Gateway forced to `workspace`** (never `--dangerously-skip-permissions`).
- **Telegram**: `allowed_chat_ids` access control + token from `TELEGRAM_BOT_TOKEN`
  env (plaintext-config warning).
- Secrets never logged / never in argv. Residuals (Windows ACL, `birkin mcp`
  operator-trust) documented. 328 tests pass.
- **Operator TODO**: move the Telegram token to `TELEGRAM_BOT_TOKEN`, set
  `allowed_chat_ids`, and rotate the token via @BotFather if it may have leaked.

## Morpheus — free + structured + secure (2026-05-29) — see ADR-028

- birkin *provides* its structured tools over MCP: `birkin/mcp_server.py`
  (`birkin mcp-serve`, stdio JSON-RPC) exposes memory, create/improve_skill, and
  approval-gated propose_action — never shell.
- The nightly Morpheus runs a **sandboxed** Claude Code session
  (`--mcp-config birkin --strict-mcp-config --allowedTools Read,Glob,Grep,
  mcp__birkin__*`) → free, structured, and **cannot run shell** unattended.
  Provider-aware: API-key configs keep birkin's own restricted loop.
- Verified: `claude` connects to the birkin MCP server + sees all 8 tools. 321 tests.

## MCP — company tool connections (2026-05-29) — see ADR-027

- The gateway runs on Claude Code, so it **inherits Claude Code's MCP servers**
  (Notion, Google Drive/Gmail/Calendar, internal HTTP/stdio, …) with no extra
  wiring — verified: the headless session loads all configured servers + their
  tools.
- birkin surface (`birkin/mcp.py`): `birkin mcp …` (pass-through to `claude mcp`)
  and `/mcp` (list + status). `gateway_allowed_tools` config → `--allowedTools`
  so the unattended gateway can call company MCP tools without a prompt.
- Connect/auth a server with `birkin mcp add …` / `claude` (Google connectors
  need a one-time auth). 300 tests pass.

## Persona (2026-05-29) — editable voice, ported from the marketing tree

- `birkin/persona.py` — user-owned `~/.birkin/SOUL.md` (warm default seeded on
  setup) + `/personality warm|concise|mentor|direct` presets + `/soul` command.
  Read fresh each turn (REPL) and injected into the persistent gateway session's
  system prompt, so edits/swaps apply with no restart. Default voice is warm and
  human (addresses the "replies aren't friendly" complaint). 295 tests pass.

## Improvement plan progress

> Improvement plan (P1–P4 from `IMPROVEMENT-PLAN.md`) was completed earlier.
> The "Hardening Roadmap" (`HARDENING-PLAN.md`) is the v0.2 work:

- **UX H7 — Inline slash-command autocomplete + line editor ✅**
  - `birkin/inline_complete.py` — stdlib-only raw-input loop with a live
    dropdown that appears the moment the user types `/`. ↑/↓ moves the
    selection, **Tab** completes (longest-common-prefix limited to
    starts-with matches, or commits the highlighted command with a
    trailing space when a single starts-with match exists or the user
    has navigated), **Enter** submits the typed line as-is, **Esc**
    dismisses the dropdown while keeping the buffer.
  - **Multi-line input** (fourth revision): Enter (`\r`) submits;
    **Shift+Enter / Ctrl+Enter / Alt+Enter** insert a literal newline at
    the cursor on terminals that support the **Kitty Keyboard Protocol**
    (Kitty, WezTerm, Alacritty, foot, Ghostty — birkin enables `CSI > 1 u`
    on REPL entry, disables on exit; non-supporting terminals ignore the
    enable byte). On terminals without the protocol the same effect is
    available via **Ctrl-J** (which sends `\n` natively); **Alt+Enter**
    also works on POSIX (it arrives as `ESC + \r`/`\n`). Pasted text keeps its embedded
    newlines and tabs verbatim — a code-snippet paste lands as typed.
    ↑/↓ navigates between lines (clamps to the shorter line's length)
    when the buffer is multi-line; on a single-line buffer they still
    drive the dropdown / persistent history. The redraw splits the
    buffer on `\n` and draws each logical line on its own screen row
    with a prompt-width indent so wrapped text aligns; per-row
    horizontal scrolling still applies (`compute_view`). The dropdown
    appears below the *last* input row.
  - **Long input + paste** (third revision): typed/pasted text is coalesced
    by the raw reader into a single ``("char", text)`` event — POSIX drains
    via zero-timeout ``select`` until a control byte appears (the byte is
    pushed back to a module-level buffer so the next call sees it); Windows
    uses ``msvcrt.kbhit`` + ``ungetwch``. Tested up to 5000-char pastes in
    one event. The redraw applies **horizontal scrolling** based on
    ``shutil.get_terminal_size`` with ``compute_view`` keeping the cursor
    visible (``…`` markers on clipped sides) so long lines don't break the
    terminal layout.
  - **Line-editor** features (second revision): cursor motion
    (←/→, Home/End, Ctrl-A/Ctrl-E), in-place insertion at the cursor,
    Delete-under-cursor (in addition to Backspace-before-cursor), and
    persistent ↑/↓ history navigation when the dropdown is inactive.
    History persists to `~/.birkin/sessions/repl_history.txt`
    (blank/consecutive-duplicate lines skipped, default cap 500).
    Pressing Esc while browsing history restores the line the user was
    drafting before they started browsing.
  - Cross-platform: POSIX termios + non-blocking ESC sequence reader
    (handles `[A/B/C/D` arrows, `[H/F`, `[1~/4~/7~/8~` Home/End, `[3~`
    Delete); Windows `msvcrt` extended-key codes (`H/P/K/M`, `G/O/S`).
    POSIX reassembles UTF-8 multi-byte input; Windows `getwch` returns
    wide characters natively (Hangul OK).
  - Non-TTY stdin/stdout transparently falls back to plain `input()`
    so scripts, harness tests, and pytest are unaffected.
  - State machine isolated as a pure transition: `EditorState` +
    `apply_event(state, event, commands, history)`. The I/O loop is the
    only side-effecting code path. 44 tests cover typing, cursor motion,
    Backspace/Delete semantics, Tab common-prefix vs commit, history
    walk + Esc-restore, Enter/Ctrl-C/Ctrl-D signaling, and on-disk
    history persistence.

- **Hardening H6 — Approval-first & skill integrity ✅**
  - **`birkin skills validate`** — new CLI command (`birkin/skills/validate.py`)
    lints every `SKILL.md` (bundled + user + extra): required frontmatter
    (`name`, `description`) errors; recommended (`version`, `license`) and the
    `## When to Use` section warn. Every Python file shipped inside a skill
    directory is run through `py_compile.compile`, so a broken bundled script
    is caught before it ever ships. Exits nonzero on any error; `--verbose`
    lists warning-only skills.
  - **Risk-tiered approval inbox** (`birkin/risk.py`): every approval category
    carries a tier — `memory`/`skill` = low, `cron` = medium, `shell` = high,
    unknown = medium (fail-safe). `birkin review` and `/api/approvals` now
    surface the tier and order pending items highest-risk-first. Risk tagging
    is **display-only** — it does not change auto-approval semantics
    (`config["auto_approve"]` still rules).
  - **Immutable official skills**: bundled (official) skills are never edited
    in place — `improve_skill` forks them into `~/.birkin/skills/<name>/`
    first (carried over from H4). `skills validate` runs against the same
    catalog so any in-place tampering would surface as an error.

- **Hardening H5 — Memory OS (polarity + version + evidence) ✅**
  - **Polarity**: every note carries `polarity: positive | negative` in
    frontmatter. The render digest tags negative notes with
    `⚠ known failure — re-verify` so the agent surfaces past failures in-context
    instead of forgetting them. Existing polarity is preserved on subsequent
    writes; invalid polarity raises `ValueError`.
  - **Version (optimistic lock)**: every note carries `version: N`; each write
    increments it by 1. Pass `expected_version` (e.g. when refining a note you
    just read) to refuse stale-snapshot overwrites — raises
    `VersionMismatchError` (the `memory_write_note` tool surfaces this as a
    friendly `is_error` instead of an exception).
  - **Evidence gate (opt-in)**: set `evidence_required: true` in config to
    require at least one `source` for any new note (default off; existing tests
    and helper-writes unchanged unless enabled).
  - Tool layer: `memory_write_note` exposes `polarity` and `expected_version`.

- **Hardening H4 — Verified learning (Skill-PR + TTL) ✅**
  - `create_skill` and `improve_skill` now **route through the approval gate**
    (category `skill`) — no skill mutates without a recorded proposal. With
    `skill` in `auto_approve` (default), the proposal is applied immediately;
    otherwise it queues for `birkin review`. `improve_skill` forks bundled
    (official) skills into the user dir instead of editing them in place.
  - `manager.apply_skill_proposal()` is the single place that writes a skill
    file; `approvals.execute_action("skill", payload)` calls it.
  - **Memory TTL**: `expires_at` frontmatter (and a `ttl_days` arg on
    `memory_write_note` / `write_note`) — expired notes are excluded from
    `list_notes`, `search`, and `render` (the prompt digest / router).
    `get_note` still returns expired notes by name (debug/inspection).
  - Default `auto_approve` renamed from the no-op `"skills"` to the matching
    category `"skill"`.

- **Hardening H3 — Reliability control plane ✅**
  - `scheduler.run_daemon` registers `atexit` + `SIGTERM` handlers that call
    `store.clear_status()` — a graceful stop or signal never leaves a dead daemon
    looking alive.
  - `store.is_status_stale(status, max_age_seconds=120)` flags a stale heartbeat;
    `/api/status` now exposes `stale: bool` and forces `daemon: false` when stale.
  - **Token budget governor** (`birkin/budget.py`): sums `estTokens` from the run
    ledger over a window and gates `Session.ask` — over-budget turns refuse with
    a clear message and write a `skipped: over-budget` run record (no LLM
    spend). `birkin budget` shows usage vs caps; dashboard surfaces it too.
    Caps default to **0 = unlimited** (no behavior change unless set).
  - **`birkin trace <run-id>`** prints a single run record for audit replay.

- **Hardening H2 — Live-LLM verification harness ✅**
  - New `live` pytest marker; offline runs deselect it
    (`addopts = "… -m 'not live'"`). Opt in with `BIRKIN_LIVE=1 pytest -m live`
    plus a backend (API key or `claude`/`codex`).
  - Live cases: chat returns non-empty reply, chat-with-tool-or-useful-reply
    (asserts a tool was actually called when running via the native loop), and
    a subagent round-trip (skipped for CLI proxy providers).
  - `scripts/smoke_live.sh` and `smoke_live.ps1` one-shots. Verified end-to-end
    against `claude-cli` (2 passed, 1 skipped) and offline (149 passed,
    3 deselected, coverage 76.80%).

- **Phase 1 — Safety & tests ✅**
  - All `subprocess` calls use **argv lists, never `shell=True`** (`proc.py`:
    `cli_argv` for CLI programs incl. Windows `.cmd` shims; `shell_argv` for the
    one intentional free-form-command path — `run_shell` and approved shell jobs).
  - **pytest suite**: **149 tests** offline, no API key, with **`pytest-cov`**
    (`coverage: 76.80%` ≥ 75% gate; interactive surfaces — `repl`, `onboarding`,
    `slashcommands`, `ui`, `menu`, `morpheus`, `nightly` (shim), `__main__` — are omitted by
    design). New offline coverage: web/server (thread `HTTPServer` + token/Host
    gates), gateway (`Gateway.handle`, `LocalHTTPChannel`), scheduler
    (`_next_nightly`, `_run_job`, status), runtime (`ConfigError`, run-record
    write, CLI system builder), llm (OpenAI mapping, `_post` retry, Anthropic
    payload `cache_control`, OpenAI parse), agent (max-turns, tool errors,
    multi tool_use), cli (parser + handlers), tools (files/shell/web/subagent),
    models, selfimprove transcript, subagent runner. `pytest`/`pytest-cov` are
    dev-only.
- **Phase 2 — Auditability ✅**
  - Every chat/agent turn writes a **run record** to `~/.birkin/runs/` (provider,
    model, tools used, iterations, usage) and appends a line to
    `~/.birkin/ledger.jsonl`. `store.estimate_usage` gives chars/words/≈tokens.
  - `birkin runs` lists recent runs + usage; the dashboard shows per-run tokens
    and tools (`agent.last_tools`/`last_iterations` feed the records).
- **Phase 3 — Config-driven runner + dry-run ✅**
  - New generic **`local-cli`** provider runs a configured argv
    (`config.cli_command`) with the prompt on stdin — any local agent/model is a
    backend without code changes (joins anthropic / openai / claude-cli /
    codex-cli; native Anthropic loop unchanged). Shown in `birkin model` when set.
  - **`birkin chat --dry-run -m "…"`** builds & prints the full prompt packet
    (system prompt + tools or routed skills + usage estimate) with **zero model
    calls and no API key** — the "packet" inspection mode.
- **Phase 4 — Skill scale & freshness ✅**
  - **Hot-reload**: `SkillManager.reload_if_changed()` (debounced mtime check)
    reloads skills when a `SKILL.md` is edited/added — called before each turn.
  - **Gating**: frontmatter `prerequisites` (`commands` / `platforms`); skills
    whose prereqs aren't met are hidden from the index and router (still loadable
    by name). e.g. an `apple-notes` mirror needing `memo` is hidden when absent.
  - **`birkin skills sync [--from DIR] [--limit N] [--force]`**: mirror upstream
    (hermes) skills into `~/.birkin/skills/mirrors/`, preserving bundled scripts
    and appending source attribution (auto-detects a local hermes skills tree).
  - **Layered prompts**: `SOUL.md` / `AGENTS.md` / `TOOLS.md` in the workspace
    (cwd) are composed into the system prompt when present.
  - Catalog grows on demand via `skills sync` plus shipped skills.

## What's built (v0.1)

| Area | Module(s) | State |
|---|---|---|
| CLI entry (single command) | `cli.py`, `__main__.py`, `pyproject` console script | ✅ |
| Agent loop (tool-calling, streaming) | `agent.py`, `llm.py` | ✅ (logic; live LLM untested — needs key) |
| LLM client (Anthropic default + OpenAI adapter) | `llm.py` | ✅ |
| Core tools (files, shell, web) | `tools/` | ✅ |
| Skills system (`SKILL.md`, hermes-compatible) | `skills/` | ✅ |
| Subagents (isolated, scoped, depth-bounded) | `subagent.py`, `tools/subagent_tool.py` | ✅ |
| **Obsidian-vault semantic memory** | `memory.py` | ✅ |
| Self-improvement (in-session `/learn`) | `selfimprove.py` | ✅ |
| **Morpheus 04:00 routine** | `morpheus.py` (legacy alias: `nightly.py`) | ✅ (dry-run + no-key handled) |
| Scheduler daemon + OS-register option | `scheduler.py` | ✅ (heartbeat verified) |
| Daily cron jobs | `cron.py` | ✅ |
| **Approval gate (human-in-the-loop)** | `approvals.py`, `store.py` | ✅ |
| Permission policy (`/permission`) | `repl.py`, `cli.py` | ✅ (memory+skills auto; rest gated) |
| **Monitoring dashboard** (not chat) | `web/` | ✅ (endpoints verified) |
| Cross-platform install one-liners | `scripts/install.sh`, `scripts/install.ps1` | ✅ |
| Seed skills (6, diverse skillsets) | `skills/` | ✅ |
| Rich slash commands (29, registry-based) | `slashcommands.py`, `ui.py` | ✅ |
| CLI model picker (`birkin model`) | `cli.py` | ✅ |
| Gateway (HTTP channel + optional Telegram) | `gateway/` | ✅ (HTTP channel verified) |
| Onboarding wizard + first-run auto-trigger | `onboarding.py` | ✅ |
| Tool enable/disable (`birkin tools`) | `cli.py`, `tools/` | ✅ |
| Design + decision docs | `docs/` | ✅ |

## Security review (addressed)

A multi-agent code review flagged 3 CRITICAL issues; all fixed:
- **Unattended shell** — the Morpheus routine now runs with a restricted toolset
  (no `run_shell`/`spawn_subagent`); consequential actions go through approval.
- **Plaintext API key** — `birkin setup` now warns, and `config.json` is written
  `chmod 600`.
- **Dashboard approve without auth** — POST now requires a per-process token
  (embedded in the page) and a localhost `Host` header (blocks DNS rebinding).
Also fixed: Anthropic SSE parser now maps deltas by block index (parallel
tool_use), `/permission add shell|cron` warns, `cron.mark_ran` is immutable.

## Verified (without an API key)

- All module imports clean; `birkin --help`.
- `birkin skills` lists 6 bundled skills (source layout **and** installed wheel).
- `uv build` produces a wheel that bundles skills under `birkin/_bundled_skills`;
  `pip install <wheel>` exposes a working `birkin` console command.
- Obsidian memory: write / list / `memory_search` / `[[wikilink]]` neighbors /
  prompt digest.
- Frontmatter parser handles real hermes nested `metadata.hermes.tags`.
- Approvals: non-auto category (`cron`) queues; auto category applies; approve
  registers a cron job and clears the pending item.
- Dashboard: `/`, `/api/status|jobs|runs|approvals|skills` all respond.
- `birkin morpheus --dry-run` degrades gracefully with no key.
- `birkin daemon` writes a status heartbeat with the correct next-Morpheus time.

## Not yet verified (requires `ANTHROPIC_API_KEY`)

- End-to-end chat: live streaming, multi-tool turns, subagent spawning.
- A real Morpheus run authoring memory/skills and proposing actions.

## Quick start

```bash
# from this repo
uv run birkin                 # chat   (or: python -m birkin)
uv run birkin web             # dashboard at http://127.0.0.1:8787
uv run birkin daemon          # Morpheus 04:00 + cron scheduler
uv run birkin morpheus        # run the Morpheus routine now (alias: birkin nightly)
uv run birkin review          # approve/reject proposed actions
uv run birkin permission      # see/adjust auto-approved categories

export ANTHROPIC_API_KEY=sk-ant-...   # required for chat / Morpheus
```

## Known limitations / next

- Daemon clears its status only on Ctrl-C (SIGINT); a hard kill (SIGTERM) leaves
  a stale `daemon: true`. Mitigation: treat a stale `heartbeat` as stopped, or
  add a SIGTERM handler.
- Memory search is keyword + `[[wikilink]]` graph (per decision); embeddings are
  a future optional upgrade.
- No automated test suite yet (manual smoke tests above). Adding `pytest`
  coverage for `frontmatter`, `memory`, `approvals`, `llm` stream parsing is the
  recommended next step.
