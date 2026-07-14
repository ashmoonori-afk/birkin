# birkin — Design Document

> Status: v0.1 (in progress) · Last updated: 2026-05-27

birkin is a **lightweight, self-improving CLI agent workspace** with skill
management, subagents, an Obsidian-vault semantic memory, a nightly
self-improvement routine, and a monitoring **dashboard** WebUI.

It is a ground-up rebuild. The previous project
([`ashmoonori-afk/birkin`](https://github.com/ashmoonori-afk/birkin), v0.8) is
treated as a reference whose **memory system is preserved in spirit** and whose
everything-else may be overhauled. Inspiration also comes from
[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)
(skills system, self-improvement loop, subagents, single-command install) and
[openclaw/openclaw](https://github.com/openclaw/openclaw) (gateway/CLI, diverse
skillsets, control UI).

---

## 1. Goals

From the project owner, in priority order:

1. **CLI-first agent workspace** runnable on macOS/Linux/Windows via a **single
   command**, like hermes.
2. **Skill management** — reflect hermes' `SKILL.md` skills system and
   openclaw's diverse skillsets.
3. **Subagents** — isolated agents for parallel / context-heavy sub-tasks.
4. **Obsidian-vault semantic memory** — *mandatory*. Persistent, transparent,
   local-first knowledge built as an Obsidian-compatible markdown vault.
5. **Self-improving** — a **nightly 04:00** routine that reviews the last 24h of
   conversation and newly added files, then improves the user's next day:
   authors/refines skills, proposes cron jobs and convenience actions, and
   **asks the user for approval before executing** anything consequential.
6. **WebUI = dashboard** — not a chat. It shows currently running/scheduled
   jobs and result summaries (and pending approvals). Chat lives in the CLI.
7. **As lightweight as possible** — minimal surface, minimal dependencies.

### Non-goals (explicitly out of scope for v0.1)

- The previous birkin's 65-node **workflow graph engine** and visual builder.
- Supporting 9+ LLM providers. v0.1 ships Anthropic (default) + an
  OpenAI-compatible adapter; more can be added later.
- A messaging gateway across 20+ chat platforms (Telegram/Slack/WhatsApp/…).
- Heavy web frameworks (FastAPI) and large test suites as a launch gate.

These may return as opt-in modules once the lightweight core is solid.

---

## 2. Design principles

Carried over from the previous birkin and reaffirmed here:

- **Compile over retrieve** — memory is *compiled* into a structured,
  human-readable wiki, not dumped into an opaque vector store.
- **Local-first** — all state lives on disk under the user's control; no
  external database; works offline except for the LLM API call.
- **Transparent** — every memory note records its source, timestamps, and
  (where relevant) confidence. Every consequential action is visible and
  approvable before it runs.
- **Minimal surface** — few commands, few files, few concepts.

Added for this rebuild:

- **Zero runtime dependencies** — Python standard library only. (`sqlite3`,
  `http.server`, `urllib`, `argparse`, `html.parser` cover our needs.)
- **Cross-platform** — no shell-specific or OS-specific assumptions in the
  core; the scheduler is a portable Python loop, not a hard dependency on
  `cron`/Task Scheduler.
- **Human-in-the-loop for autonomy** — the agent may *propose* freely but must
  get explicit approval before executing anything that changes the world
  outside the vault/skills (e.g. registering cron jobs, running commands).

---

## 3. Architecture overview

```
                         ┌──────────────────────────────┐
            CLI chat  ───▶│  Agent loop (tool-calling)   │
         (birkin chat)    │  agent.py + llm.py           │
                         └──────────────┬───────────────┘
                                        │ tools
        ┌───────────────┬──────────────┼───────────────┬───────────────┐
        ▼               ▼              ▼               ▼               ▼
   files/shell/web   skills mgr    subagents       memory          remember
   (tools/*.py)      (skills/*)    (subagent.py)   (Obsidian vault) (vault write)
                                        │
                                        ▼
                              isolated child Agent

   ┌─────────────────────────── self-improvement ───────────────────────────┐
   │  scheduler.py (daemon)  ──04:00──▶  morpheus.py ──proposes──▶ store.py   │
   │       │                                                  (runs, pending, │
   │       └── due cron jobs ───────────────────────────────▶  cron, status) │
   └──────────────────────────────────────────────────────────────┬─────────┘
                                                                    │ reads
                          approvals.py (CLI review)  ◀──────────────┤
                          WebUI dashboard (web/*)     ◀──────────────┘
```

### Module map

| Module | Responsibility |
|---|---|
| `birkin/cli.py` | argparse entry: `chat`, `skills`, `web`, `setup`, `nightly`, `daemon`, `review` |
| `birkin/config.py` | birkin home, config load/save, API-key resolution, vault path |
| `birkin/llm.py` | provider-agnostic client (Anthropic streaming; OpenAI adapter) |
| `birkin/agent.py` | the tool-calling loop (provider/skill agnostic) |
| `birkin/prompts.py` | system-prompt construction (progressive disclosure) |
| `birkin/tools/` | `files`, `shell`, `web`, `subagent_tool`; registry + context |
| `birkin/skills/` | `frontmatter` parser, `loader`, `manager` (load/create/improve) |
| `birkin/subagent.py` | isolated child-agent runner |
| `birkin/memory.py` | **Obsidian-vault semantic memory** (compile/search/link) |
| `birkin/runtime.py` | wires a `Session` for both CLI and dashboard |
| `birkin/repl.py` | interactive CLI chat |
| `birkin/store.py` | JSON state: runs, pending approvals, cron jobs, heartbeat |
| `birkin/morpheus.py` | the 04:00 self-improvement routine |
| `birkin/scheduler.py` | cross-platform daemon (nightly + due cron jobs) |
| `birkin/cron.py` | register/list/run cron jobs |
| `birkin/approvals.py` | review/approve/reject + execute approved actions |
| `birkin/web/` | dashboard HTTP server + single-page UI |
| `skills/` | bundled `SKILL.md` skills |

---

## 4. Memory — Obsidian-vault semantic memory (mandatory)

The signature subsystem, preserved from the previous birkin and required to use
an **Obsidian vault**.

**Storage.** A directory of markdown notes (default `~/.birkin/vault`,
configurable via `vault_path`). Each note is Obsidian-compatible:

```markdown
---
title: FlowerPlus GTM
type: project            # person | project | preference | fact | topic | session
created: 2026-05-27
updated: 2026-05-27
confidence: 0.8          # 0–1, how sure we are
sources: ["session:2026-05-27-1012"]
tags: [marketing, gtm]
---

FlowerPlus is a corporate-welfare flower subscription play. Related to
[[Outbound Sales Script]] and [[User Research Report]].
```

**Compile over retrieve.** Conversations and added files are *compiled* into
notes — entities extracted, classified, and connected with `[[wikilinks]]` —
rather than chunked into a vector index. This keeps memory inspectable in
Obsidian and editable by hand.

**Operations (tools the agent can call).**

- `remember` — quick capture of a durable fact (kept for compatibility).
- `memory_write_note` — create/update a vault note (title, type, body, tags,
  links, confidence, source).
- `memory_search` — keyword/substring search across the vault (stdlib; no
  embeddings). Returns matching notes with context.
- `memory_get_note` — read a note in full.
- `memory_link` — add a `[[wikilink]]` between two notes.

**Prompt injection.** A compact memory digest (recent/important notes) is
rendered into the system prompt each turn via `Memory.render()`; the agent
pulls full notes on demand with `memory_get_note` / `memory_search`
(progressive disclosure, same pattern as skills).

**Transparency & decay.** Notes carry `sources`, `created`/`updated`, and
`confidence`. A soft-decay convention (older, low-confidence, unreferenced
notes are de-prioritized in the digest) approximates the previous project's
"natural decay"; nothing is deleted automatically.

---

## 5. Skills system

`SKILL.md` directories compatible with the agentskills.io / hermes standard:
YAML frontmatter (`name`, `description`, `version`, `metadata.*.tags`) plus a
markdown body (with `When to Use` / `When NOT to Use`).

- **Discovery**: bundled `skills/` + user `~/.birkin/skills/` + extra dirs;
  user skills shadow bundled ones on name collision.
- **Progressive disclosure**: the model sees only a one-line index per skill and
  calls `load_skill` for the full text.
- **Self-authoring**: `create_skill` writes a new skill; `improve_skill`
  appends a dated "Learned" note. This is the substrate for self-improvement.

---

## 6. Subagents

`spawn_subagent` delegates a self-contained task to an isolated `Agent`:
fresh conversation, scoped toolset, optional preloaded skills, shares the LLM
client and skill catalog, runs on the cheaper `subagent_model`, and does **not**
write to memory. Recursion is bounded by `max_depth` (default 2).

---

## 7. Self-improvement — the nightly 04:00 routine

The defining autonomy feature.

**Trigger.** `scheduler.py` runs as a daemon (`birkin daemon`) and wakes at the
configured hour (`nightly_hour`, default `4`). It also runs due cron jobs.
`birkin nightly` runs the routine immediately on demand.

**Inputs.** The routine gathers:
- the last 24h of **conversation** (saved sessions + a rolling activity log), and
- **files added or changed** in the workspace in the last 24h (by mtime).

**What it does (a "night agent" run).**
1. **Compile memory** — update the Obsidian vault with new entities, facts, and
   links from the day's conversations and files.
2. **Author skills** — create/refine `SKILL.md` skills for repeatable
   procedures it observed. *(Safe; applied directly.)*
3. **Propose convenience actions & cron jobs** — e.g. "schedule a 09:00 digest",
   "pre-fetch X every morning". These are **not executed**. They are written to
   a **pending-approval queue**.

**Human-in-the-loop gate.** Anything that changes the world outside the
vault/skills (registering a cron job, running a command, sending anything
external) becomes a *proposal* in `~/.birkin/pending/`. The user reviews with
`birkin review` (or the dashboard) and approves/rejects. Only approved actions
execute.

**Output.** Each run writes a **summary** to `~/.birkin/runs/` (what it learned,
what it changed, what it is proposing) — surfaced on the dashboard.

---

## 8. WebUI — monitoring dashboard (not chat)

A small standard-library HTTP server serving a single-page dashboard. It is
**read-mostly** and reflects state written by the daemon/nightly routine.

**Panels.**
- **Status** — model, vault path, skills count, daemon running?, next nightly.
- **Jobs** — currently running jobs + scheduled jobs (nightly + cron).
- **Recent runs** — summaries of recent nightly/cron runs.
- **Pending approvals** — proposed actions with **Approve / Reject** buttons.
- **Skills & memory** — catalog counts and quick stats.

**Endpoints.** `GET /api/status`, `/api/jobs`, `/api/runs`, `/api/skills`,
`GET/POST /api/approvals`. Chat is intentionally absent — use `birkin chat`.

### 8.1 Workbench design system

The WebUI is a compact local monitoring workbench, not a general-purpose IDE.
Its information architecture follows the selected GitHub Mission Control
reference, its dark density and three-pane rhythm follow the selected VS Code
Agents Window reference, and its proposal scan uses only the selected Replit
task-board traits: counts, timestamps, explicit empty states, and actions
anchored to each row. Replit's Drafts/Active/Ready/Done lifecycle columns are
explicitly excluded.

**Reference contract.** The only visual references are
`github-mission-control.jpg`, `vscode-agents-window.png`, and
`replit-task-board.png` in the approved research artifact set. Their roles are
structure, style, and proposal scan behavior respectively; no product copy,
logos, or unrelated IDE surfaces are copied.

**Tokens.** All values are CSS custom properties in `index.html`.

| Group | Tokens |
|---|---|
| Canvas | `--canvas #181818`, `--rail #181818`, `--sidebar #181818`, `--workspace #1f1f1f`, `--surface #242424`, `--surface-raised #292929` |
| Lines | `--line #303030`, `--line-strong #3a3a3a`, `--focus #75beff` |
| Type | `--text #d4d4d4`, `--text-strong #f0f0f0`, `--muted #969696`, `--faint #6f6f6f`, system UI body, system mono metadata |
| State | `--accent #3794ff`, `--accent-soft #102f48`, `--good #4ec9b0`, `--warn #cca700`, `--danger #f14c4c` |
| Space | 4px base rhythm; 8px compact gap; 12px row inset; 16px section inset |
| Shape | 4px controls, 6px panels; no pill treatment except compact status/count badges |

**Responsive geometry.** At 1024px and above the shell is a 48px activity
rail, a 224px navigation sidebar, and a fluid workspace. Below 1024px the rail
is removed. Below 720px the sidebar becomes a sticky horizontal tab strip and
the workspace becomes a single column. The supported widths are 320, 375, 768,
and 1280px with no horizontal document overflow.

**Primitives and states.** `ActivityButton`, `NavTab`, `StatusBadge`,
`MetricCell`, `WorkbenchPanel`, `DenseRow`, `EmptyState`, and `ActionButton`
are the reusable visual primitives. Every data panel exposes loading, populated,
empty, and retained-last-good error states. Controls expose default, hover,
active, disabled, and keyboard-focus states. Proposal actions keep Approve and
Reject attached to their row and disable while the request is in flight.

**Interaction and accessibility.** Overview, Proposals, Jobs, Runs, and Skills
are the only views. Tabs implement arrow-key, Home, and End navigation; focus
is always visible; errors are announced through a polite live region; the
document includes a skip link and semantic landmarks. Touch targets expand to
44px for coarse pointers, motion is limited to opacity/transform state changes,
and `prefers-reduced-motion` removes transitions. Last-known-good data remains
visible during refresh failures, with a timestamped connection notice and an
explicit retry action.

**Personas and accepted debt.** The primary persona is an operator scanning
runtime state by keyboard or pointer; the secondary persona is a reviewer who
must make deliberate approval decisions without losing list context. The page
uses native browser APIs and inline SVG only to preserve the zero-dependency
runtime. Advanced filtering, sortable columns, charts, theming, chat, files,
terminal, sessions, and configuration are intentionally out of scope until
real monitoring volume demonstrates a need.

---

## 9. Cross-platform & single-command

- **One command**: a `birkin` console script (via `pyproject.toml`) plus
  `python -m birkin`. Installable with `uv`, `pipx`, or `pip`.
- **Install one-liners** (hermes-style):
  - macOS/Linux: `curl -fsSL <raw>/scripts/install.sh | bash`
  - Windows: `irm <raw>/scripts/install.ps1 | iex`
  These set up an isolated environment and put `birkin` on `PATH`.
- **Portable scheduler**: a Python loop, not a hard dependency on `cron` or
  Windows Task Scheduler. (Optional OS-native registration can be layered on.)
- **Portable paths**: `pathlib` + `~/.birkin`; no hard-coded separators.

---

## 10. Tech stack

- **Language**: Python ≥ 3.10 (developed on 3.13).
- **Dependencies**: none at runtime (standard library only). `pytest` for dev.
- **Build**: `hatchling`. **Run/install**: `uv` / `pipx` / `pip`.
- **LLM**: Anthropic Messages API (streaming via `urllib`); OpenAI-compatible
  adapter. Prompt caching enabled for the system prompt and tool list.

---

## 11. Configuration

`~/.birkin/` (override with `$BIRKIN_HOME`):

```
~/.birkin/
├── config.json     # provider, model, vault_path, nightly_hour, options
├── vault/          # Obsidian semantic memory (markdown notes)
├── skills/         # user- and agent-authored skills
├── sessions/       # saved conversations (nightly input)
├── runs/           # nightly/cron run summaries (dashboard)
├── pending/        # proposed actions awaiting approval
├── cron.json       # registered cron jobs
└── status.json     # daemon heartbeat / next-run info
```

Secrets are read from the environment first (`ANTHROPIC_API_KEY` /
`OPENAI_API_KEY`) and only fall back to `config.json` if explicitly set there.

---

## 12. Roadmap / open questions

- Embedding-based semantic search as an *optional* upgrade over keyword search.
- OS-native scheduler registration (`crontab` / `schtasks`) as an opt-in for
  survival across reboots without a long-running daemon.
- Re-introducing a (much smaller) workflow/trigger system if needed.
- Test suite expansion toward the previous project's coverage bar.

See [DECISIONS.md](./DECISIONS.md) for the rationale behind these choices.
