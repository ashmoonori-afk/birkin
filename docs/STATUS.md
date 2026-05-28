# birkin — Build Status

> Snapshot: 2026-05-28 · v0.1 (initial rebuild)

A concise, kept-current summary of what exists and how to run it. For the full
design see [DESIGN.md](./DESIGN.md); for rationale see [DECISIONS.md](./DECISIONS.md).
Improvement roadmap: [IMPROVEMENT-PLAN.md](./IMPROVEMENT-PLAN.md).

## Improvement plan progress

- **Phase 1 — Safety & tests ✅**
  - All `subprocess` calls use **argv lists, never `shell=True`** (`proc.py`:
    `cli_argv` for CLI programs incl. Windows `.cmd` shims; `shell_argv` for the
    one intentional free-form-command path — `run_shell` and approved shell jobs).
  - **pytest suite** added under `tests/` — **48 tests**, offline, no API key
    (frontmatter, memory vault, skills route/render, approvals, store, cron,
    Anthropic SSE parser incl. parallel tool_use, agent loop + nudge triggers,
    proc helpers). `pytest` is a dev-only extra.
- **Phase 2 — Auditability ✅**
  - Every chat/agent turn writes a **run record** to `~/.birkin/runs/` (provider,
    model, tools used, iterations, usage) and appends a line to
    `~/.birkin/ledger.jsonl`. `store.estimate_usage` gives chars/words/≈tokens.
  - `birkin runs` lists recent runs + usage; the dashboard shows per-run tokens
    and tools (`agent.last_tools`/`last_iterations` feed the records).
- Phases 3–4 (config-driven runners + dry-run, skill hot-reload/sync/gating +
  layered prompts) — pending.

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
