# birkin — Build Status

> Snapshot: 2026-05-28 · v0.1 (initial rebuild)

A concise, kept-current summary of what exists and how to run it. For the full
design see [DESIGN.md](./DESIGN.md); for rationale see [DECISIONS.md](./DECISIONS.md).
Improvement roadmap: [IMPROVEMENT-PLAN.md](./IMPROVEMENT-PLAN.md).

## Improvement plan progress

> Improvement plan (P1–P4 from `IMPROVEMENT-PLAN.md`) was completed earlier.
> The "Hardening Roadmap" (`HARDENING-PLAN.md`) is the v0.2 work:

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
    `slashcommands`, `ui`, `menu`, `nightly`, `__main__` — are omitted by
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
| **Nightly 04:00 routine** | `nightly.py` | ✅ (dry-run + no-key handled) |
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
- **Unattended shell** — the nightly routine now runs with a restricted toolset
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
- `birkin nightly --dry-run` degrades gracefully with no key.
- `birkin daemon` writes a status heartbeat with the correct next-nightly time.

## Not yet verified (requires `ANTHROPIC_API_KEY`)

- End-to-end chat: live streaming, multi-tool turns, subagent spawning.
- A real nightly run authoring memory/skills and proposing actions.

## Quick start

```bash
# from this repo
uv run birkin                 # chat   (or: python -m birkin)
uv run birkin web             # dashboard at http://127.0.0.1:8787
uv run birkin daemon          # nightly 04:00 + cron scheduler
uv run birkin nightly         # run the routine now
uv run birkin review          # approve/reject proposed actions
uv run birkin permission      # see/adjust auto-approved categories

export ANTHROPIC_API_KEY=sk-ant-...   # required for chat/nightly
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
