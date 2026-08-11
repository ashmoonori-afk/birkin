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
5. **Self-improving** — a **daily 07:00** routine that reviews the last 24h of
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

- **Explicit, bounded dependencies** — the core remains mostly standard
  library, while active voice declares the official OpenAI SDK plus realtime
  and audio helpers in `pyproject.toml`.
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
│  scheduler.py (daemon)  ──07:00──▶  morpheus.py ──proposes──▶ store.py   │
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
| `birkin/morpheus.py` | the 07:00 self-improvement routine |
| `birkin/scheduler.py` | cross-platform daemon (nightly + due cron jobs) |
| `birkin/cron.py` | register/list/run cron jobs |
| `birkin/approvals.py` | review/approve/reject + execute approved actions |
| `birkin/web/` | dashboard HTTP server + single-page UI |
| `birkin/voice/` | validated config, one-turn controller, clap/phrase wake, microphone/WAV capture, GPT STT/TTS, Gateway client, background mission wiring |
| `birkin/background.py` | bounded daemon queue, admission backpressure, cancellation, shutdown |
| `birkin/background_receipts.py` | immutable snapshots, ordered events, atomic JSON receipts |
| `skills/` | bundled `SKILL.md` skills |

### Active voice control

The shipped voice path is deliberately chained rather than a second agent loop:

```text
PCM16/24 kHz microphone or WAV
  -> clap + normalized phrase gate
  -> gpt-transcribe (recorded/in-memory audio)
  -> foreground filler TTS starts
     concurrently with GatewayClient POST {"channel":"voice", "session":..., "text":...}
  -> existing Gateway.handle() provider session, tool, and approval boundary
  -> foreground reply or bounded BackgroundBroker receipt
  -> gpt-4o-mini-tts PCM
  -> speaker and/or configured file sink
```

`voice.stt_model` defaults to `gpt-transcribe`; the executable minimum uses
bounded recorded/in-memory windows so the same path can be driven by microphone
hardware, recorded fixtures, and deterministic tests. A future
`gpt-realtime-2.1` conversational mode must remain opt-in because direct
speech-to-speech cannot silently replace the existing text/approval boundary.
Foreground mode speaks the concise `voice.filler_text` acknowledgement while
the Gateway turn is pending, rather than delaying request dispatch; an empty
value disables it. The voice client remains provider-neutral, so the configured
Gateway session continues to own Claude or Codex OAuth authentication.

Wake is never authorization. `GatewayClient` accepts only an exact loopback
HTTP `/message` endpoint, without credentials, query, or fragment; HTTPS and
non-loopback hosts are rejected. `BIRKIN_HTTP_TOKEN`, when configured, is sent
only across that validated boundary. Local HTTP caps JSON bodies at 1 MB,
bounds body reads at two seconds, requires complete payloads, accepts only
string text plus `http` or `voice` channels, and rejects `telegram` spoofing.
Gateway's approved-work state still requires a trusted Telegram workflow, so a
destructive voice command stays unapproved. Raw audio remains in memory unless
the caller explicitly supplies a file sink, and API credentials are read from
`OPENAI_API_KEY`.

The background lane uses a bounded daemon worker queue with non-blocking
backpressure, immutable job snapshots, monotonically sequenced events,
cancellation before start, and an atomically replaced JSON receipt at every
transition. One-shot CLI mode prints the ACK and receipt before awaiting
delivery; timeout cleanup does not block on a still-running worker or retain
interpreter exit. A persistent controller can keep the same broker alive
across turns.

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

## 7. Self-improvement — the daily 07:00 routine

The defining autonomy feature.

**Trigger.** `scheduler.py` runs as a daemon (`birkin daemon`) and wakes at the
configured hour (`morpheus_hour`, default `7`). It also runs due cron jobs.
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
execute. Telegram long-work proposals share the same on-disk queue but are
chat-bound and intentionally resolved only by their Telegram buttons; generic
CLI/dashboard approval lists omit them.

**Output.** Each run writes a **summary** to `~/.birkin/runs/` (what it learned,
what it changed, what it is proposing) — surfaced on the dashboard.

---

## 8. WebUI — monitoring dashboard (not chat)

A small standard-library HTTP server serves a single-page, read-mostly
monitoring workbench for Overview, Proposals, Jobs, Runs, and Skills. It
reflects state written by the daemon/nightly routine. Chat remains
intentionally absent — use `birkin chat`.

### Locked visual and interaction contract

The selected-reference contract is owner-locked and exclusive:

- **B STRUCTURE — operations hierarchy and scan flow:** `C:\Users\lg\Documents\Claude\Projects\Birkin\.omo\teams\team-ae9e376f\artifacts\real-product-screens\github-mission-control.jpg` (`sha256:b5d34b8aff00427a7e7dd5107fdf2123159bacecdf84b8cf581d5e09f1ffaf80`). Use its navigation, collection, selected-detail, and persistent-status hierarchy. Do not copy brand marks or product-specific copy.
- **A STYLE — compact workbench language:** `C:\Users\lg\Documents\Claude\Projects\Birkin\.omo\teams\team-ae9e376f\artifacts\real-product-screens\vscode-agents-window.png` (`sha256:abe56f8953f366f343d811467f34de4e767a942c6b69139cc8db0c0414825b03`). Use compact charcoal surfaces, native/system typography, crisp 1px separators, dense rows, restrained blue focus/selection, and clear panel/tab boundaries. Exclude its chat composer, file tree, editor, terminal, brand marks, and product-specific copy.
- **C APPROVAL STRUCTURE — truthful explicit decisions:** `C:\Users\lg\Documents\Claude\Projects\Birkin\.omo\teams\team-ae9e376f\artifacts\real-product-screens\replit-task-board.png` (`sha256:839a3f36ab104245b05ce35c173fc7c07244fd021d18c94b71e853e9feac8a7e`). Use proposal queue -> selected review -> explicit approve/reject -> truthful inline result or recovery. Exclude fake lifecycle states and unsupported mutations.

These references govern only their named roles. Earlier selected-reference choices are superseded; compatible accessibility and spacing research may remain secondary, but no fourth selected reference or copied product identity may override this contract. Birkin's monitoring-only scope, domain vocabulary, current-version rule, source/wheel parity, and accepted-debt boundary remain authoritative.

### 2.1 Tokens

| Class | Exact values |
| --- | --- |
| Color | `--bg:#0f1115`; `--surface:#161922`; `--surface-raised:#1d212c`; `--border:#657084`; `--text:#e6e9ef`; `--muted:#a7afbf`; `--accent:#7aa2f7`; `--focus:#a9c7ff`; `--success:#9ece6a`; `--warning:#e0af68`; `--danger:#f7768e`; no undeclared literal color outside `:root`. `#657084` is the sole boundary color and must measure >=3:1 against every locked dark surface. |
| Type | native stack `ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif`; body `14px/1.5`; label `12px/1.4` weight 600 letter-spacing `.04em`; title `20px/1.2` weight 650; resource title `14px/1.35` weight 600; data/code `12px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace` |
| Space | `--s1:4px`; `--s2:8px`; `--s3:12px`; `--s4:16px`; `--s5:24px`; `--s6:32px`; row minimum `44px`; panel padding `16px`; grid gap `12px` |
| Shape/depth | radius `6px` controls, `8px` panels; one `1px solid var(--border)` boundary; no shadow; selected row has `inset 3px 0 0 var(--accent)` |
| Focus/motion | focus `2px solid var(--focus)` with `2px` offset; one transition `color,background-color,border-color 160ms ease-out`; `prefers-reduced-motion:reduce` makes duration `0.01ms`; no transform, parallax, shimmer, or decorative animation |
| Contrast | normal text and state text >=4.5:1, large text >=3:1, focus/UI boundaries >=3:1; state never color-only |

### 2.2 Layout and responsive behavior

| Width | Exact layout |
| --- | --- |
| `>=1024px` | `48px` top bar; body height `calc(100dvh - 80px)`; columns `176px minmax(280px,360px) minmax(0,1fr)`; `32px` status strip; rail/list/detail scroll independently; page body does not mega-scroll |
| `768..1023px` | columns `160px minmax(260px,320px) minmax(0,1fr)`; same top/status heights and independent scroll |
| `<=767px` | top bar `48px`; five destinations become one horizontally scrollable but keyboard-reachable `44px` nav row; exactly one of collection or detail is visible; selecting a row stores `{resource,key,index}` as the origin then shows detail; the first detail control is `Back to Overview`, `Back to Proposals`, `Back to Jobs`, `Back to Runs`, or `Back to Skills`, matching the active destination; Back switches to list, re-queries the stable key, and focuses it; if absent it focuses the row now at the stored index, otherwise the previous row, otherwise the destination heading; status strip is `min-height:32px` and may wrap without horizontal page overflow |
| `320/375px and 200% zoom` | `html`, `body`, workspace, rows, preformatted data use `min-width:0`, wrapping/`overflow-wrap:anywhere`; `document.documentElement.scrollWidth <= clientWidth`; no clipped Korean, 200-character English, or nested JSON |

### 2.3 Primitive states

- Rail item: default muted; hover raised surface; active `aria-current="page"`, text + accent inset; focus exact outline; disabled native `disabled` where applicable.
- Resource row: native button, `data-resource` and stable `data-key`; selected `aria-pressed="true"` plus accent inset. The nouns are exactly `proposals`, `jobs`, `runs`, and `skills`: loading is `Loading proposals...` (or the matching noun), empty is `No proposals found.`, and error is adjacent `role="alert"` text `Could not load proposals. Retrying.`. Stale is warning text `Last update is stale.`; no skeleton animation.
- Detail: heading receives `tabindex="-1"`; data is label/value `dl`; nested payload is escaped `pre`; Back behavior follows the width table.
- Proposal action: buttons are at least 44px; one action sets the row `aria-busy="true"` and disables both buttons; success announces once in `#action-status[role=status]` and then chooses next row, previous row, or destination heading in that order; HTTP non-2xx, invalid JSON, or JSON `ok !== true` retains row and focus and shows one adjacent `role=alert`; repeated activation while busy sends no request.
- Global sync: `#sync-state[role=status]` says exactly `Updated ` followed by `Intl.DateTimeFormat().format(new Date())`, `Updating...`, `Paused while hidden`, `Connection lost; retrying`, or `Last update is stale`; unchanged polls do not announce.

### Locked navigation, focus, announcements, personas, and debt

- Overview uses the middle pane as a fixed `System snapshot` collection with four rows in order: `Runtime`, `Daemon`, `Budget`, `Queue`. Runtime is selected initially. Mobile origin state is retained independently of DOM presence and Back follows the stable-key/index/previous/heading fallback in the width table.
- On desktop/tablet, destination activation focuses the destination heading; row activation keeps focus on that row while the detail updates. Background refresh never moves focus. On mobile, row activation switches list -> detail, then focuses the detail heading; `Back to <destination>` switches detail -> list before restoring the originating row.
- Proposal busy strings are exactly `Approving proposal...` and `Rejecting proposal...`. Success strings are `Proposal approved.` and `Proposal rejected.`. Failure strings are `Could not approve proposal. Try again.` and `Could not reject proposal. Try again.`; raw server text is not announced. On mobile success, switch to the list before focusing next row, previous row, or the destination heading.
- Named personas and binary exits are fixed. `keyboard_operator`: traverse destination -> collection row -> detail -> proposal action -> mobile Back without mouse; visible focus never lands on `body`, reorder retains the same node, failure retains the action row, and Back restores the originating row. `screen_reader_operator`: landmarks/names are unique; the active destination has `aria-current="page"`; selected rows expose state; each error is one adjacent `role="alert"`; sync/action updates are deduplicated `role="status"`. `low_vision_operator`: at 200% zoom and 320/375/768/1280 widths no page horizontal overflow or clipped text occurs, text/state/focus contrast meets 4.5:1/3:1/3:1. `reduced_motion_operator`: the media query reduces the sole transition to `0.01ms` and no transform, parallax, shimmer, or decorative animation exists. `mobile_on_call`: 44px controls, one list/detail pane, first detail control `Back to <destination>`, deterministic focus return, and status may wrap. `cjk_long_data_operator`: Korean, a 200-character English string, and nested JSON wrap without loss and remain inert text. Every design/visual verdict contains one assertion ID per persona and all six must pass.
- Exit criteria are exact: every Must/Must-NOT contract assertion passes; all six persona assertions pass at every applicable viewport; C001-C003 schemas validate; full tests and scoped `git diff --check` pass; source/wheel parity and performance gates pass; every named review has its accepted native verdict (`PASS`, `APPROVE`, or `OKAY` as defined for that artifact) with non-empty evidence; unrelated bytes are unchanged; resources close; patch integrates; durable goal completes.
- Accepted debt is exactly one item: `DEBT-WEB-001`, the standard-library serial HTTP server can pause dashboard refresh while a long proposal action executes. This task does not change server concurrency; the UI exposes busy state, suppresses poll commits during the action, and performs exactly one reconciliation afterward. No other debt is accepted; reviewers must reject any additional deferred item regardless of severity.

### API-to-surface mapping and preserved contracts

All current endpoint envelopes and status codes remain unchanged. `/api/status.version = birkin.__version__` is additive. `Handler.server_version` is derived from the same imported version as `birkin-dashboard/<version>`. Skill discovery failure is truthful: `/api/status` returns `skills_count:null` and a stable `skills_error:"unavailable"` marker without raw exception text, while `/api/skills` retains its current success array and HTTP 500 `{"error":"..."}` failure envelope. Client `getJSON` treats non-2xx, invalid JSON, and wrong top-level type as errors and maps them to the primitive error state.

| Endpoint/source | Destination and exact fields |
| --- | --- |
| `/api/status` | Overview detail: `provider`, `model`, `vault`, `skills_count`, `skills_error` only when discovery is unavailable, `auto_approve`, `daemon`, `stale`, `next_morpheus` falling back to `next_nightly`, `morpheus_hour` falling back to `nightly_hour`, `pending_count`, `heartbeat`, `budget.used_today`, `budget.used_month`, `budget.daily_cap`, `budget.monthly_cap`, `budget.over_daily`, `budget.over_monthly`, and additive `version`. Status strip: daemon/stale, pending count, budget-over state, heartbeat freshness, version. Missing values render em dash, skill failure renders `Unavailable`, never zero/running. |
| `/api/approvals` | Proposals collection/detail: `id` key; `risk`, `category`, `title`, `description`, `created`, `origin`, escaped `payload`, Approve/Reject. Render server order. Server comparator is `critical > high > medium > low`; unknown/missing category is medium; Python stable sort preserves original filename order within a tier. Tests cover missing risk/category and stable ties. |
| `/api/jobs` | Jobs collection/detail: envelope `status` only supplies daemon context; each job uses `id` key, `name`, `enabled`, `type`, zero-padded local `hour:minute`, native `last_run`, `created`, `deliver_chat_id`; `value` is displayed only in escaped detail. Do not invent `next_run` or `last_attempt`. Preserve API order. |
| `/api/runs` | Runs collection/detail: `id` key, `kind`, `at`, `summary`, `usage.estTokens`, `details.tools`, and escaped full `details`. Newest file order from `store.list_runs`; only records passing the W1-T1 run predicate reach consumers. |
| `/api/skills` | Skills collection/detail: `name` key, `description`, `source`; alphabetical server order. No skill action. |

Overview mapping is exact:

| Row | Collection summary | Detail labels in order | Formatting / missing rule |
| --- | --- | --- | --- |
| `Runtime` | `v<version> · <provider>/<model>` | `Provider`, `Model`, `Vault`, `Version`, `Skills` | missing scalar is `—`; `skills_error=="unavailable"` renders `Unavailable` regardless of prior count, otherwise integer `skills_count` |
| `Daemon` | `Stale heartbeat`, else `Running` when `daemon===true`, else `Stopped` | `State`, `Heartbeat`, `Next Morpheus`, `Morpheus hour` | state precedence is stale > running > stopped; `next_morpheus ?? next_nightly`; `morpheus_hour ?? nightly_hour`; time strings use the existing local date formatter, missing is `—` |
| `Budget` | `Over budget` when either over flag is true, else `<used_today> today` | `Used today`, `Daily cap`, `Used month`, `Monthly cap` | numeric values use `Intl.NumberFormat`; cap `0` is `Unlimited`; missing is `—`; collection text never infers a percentage |
| `Queue` | `<pending_count> pending` | `Pending proposals`, `Auto-approve categories` | pending defaults to `0` only when the field is a finite number; auto-approve is the received array joined by `, ` or `None`; wrong type is `—` |

Non-Overview collection/detail placement is exact:

| Destination | Collection primary / secondary | Detail labels in order | Missing / wrong-type rule |
| --- | --- | --- | --- |
| `Proposals` | primary `title`; secondary `<risk-or-category> · <created>` | `Risk`, `Category`, `Description`, `Created`, `Origin`, `Payload`, then Approve/Reject controls | non-string scalar is `—`; payload accepts any JSON and is escaped; missing id rejects the row; received order is preserved after server priority sort |
| `Jobs` | primary `name`; secondary `<enabled-state> · <type> · <HH:MM>` | `Name`, `Enabled`, `Type`, `Schedule`, `Last run`, `Created`, `Deliver chat ID`, `Value` | `enabled` must be boolean or `—`; hour/minute must be finite numbers or schedule `—`; value is escaped detail only; missing/non-string id rejects the row |
| `Runs` | primary `summary`; secondary `<kind> · <at>` | `Kind`, `At`, `Summary`, `Estimated tokens`, `Tools`, `Details` | W1-T1 predicate rejects invalid id/kind/at/summary before rendering; `usage.estTokens` requires finite number; `details.tools` requires array and joins escaped scalars, otherwise `—`; full details is escaped |
| `Skills` | primary `name`; secondary `source` | `Name`, `Description`, `Source` | missing/non-string name rejects the row; missing/non-string description or source is `—`; alphabetical server order is preserved |

The status strip order is exactly `Daemon: <state>` · `Proposals: <pending>` · `Budget: Over|Within|Unlimited` · the `#sync-state` text · `v<version>`. Budget status is `Over` when either over flag is true; otherwise it is `Unlimited` only when both caps are numeric zero; otherwise it is `Within`. A missing field renders `—`; an endpoint error retains the last-good value and marks its surface stale rather than inventing a value.

`store.list_runs` predicate is exact: the decoded value must be a dictionary and each of `id`, `kind`, `at`, and `summary` must be a string, with `id`, `kind`, and `at` non-empty. Filtering occurs before applying `limit`; invalid JSON, lists, process-registry dictionaries, and incomplete dictionaries are skipped.

### Polling state machine

The only owner is `scheduleRefresh(delayMs)` using completion-scheduled `setTimeout`; fixed `setInterval` is forbidden. Normal delay is `5000ms`; failure delay is `5000ms`; first refresh is immediate. The initial cycle and a retry after a Skills error issue five GETs strictly sequentially in this order: `/api/status` -> `/api/approvals` -> `/api/jobs` -> `/api/runs` -> `/api/skills`. Every other steady cycle issues exactly four GETs in this order: `/api/status` -> `/api/approvals` -> `/api/jobs` -> `/api/runs`; it retains last-good Skills. A successful five-GET cycle clears the Skills-error retry flag; a failed Skills GET sets it so the next visible cycle is five again. `Promise.all` and endpoint overlap are forbidden, so both unresolved logical cycles and unresolved fetches are at most one. `runningCycle` and one boolean `dirty` cap logical refresh cycles at one in flight. Every cycle and proposal action receives a monotonically increasing generation; a response from an older generation, from a cycle completed while hidden, or from a cycle superseded by a proposal POST is discarded before any DOM commit.

| Event / prior state | Requests | DOM commit | Next state/timer |
| --- | --- | --- | --- |
| initial / visible idle | one cycle immediately | keyed reconcile changed signatures | idle; schedule 5000ms after completion |
| timer / visible idle | one cycle | only surfaces whose canonical JSON signature changed | idle; schedule 5000ms after completion |
| trigger / running | none; set `dirty=true` | none | after completion run exactly one immediate coalesced cycle, then schedule |
| document becomes hidden / idle | clear owned timer | none | hidden; `Paused while hidden`; zero requests |
| document becomes hidden / running | do not abort response; set hidden | do not commit response | hidden after completion; zero new requests |
| document visible / hidden | one immediate cycle | reconcile newest response | idle; schedule after completion |
| any fetch/non-2xx/type error | no replacement of last good rows | sync error + affected surface alert once | idle; retry after 5000ms |
| recovery after error | one cycle | clear error; reconcile | idle; normal 5000ms |
| proposal POST starts / idle | one POST; invalidate any earlier cycle generation and set action owner | busy row only; no poll response commits during action | poll triggers coalesce into dirty |
| proposal POST success `2xx && json.ok===true` | no duplicate POST; schedule exactly one immediate four-GET post-action reconciliation cycle | publish success once, reconcile that cycle, then focus next, previous, heading from the reconciled DOM | idle; schedule 5000ms after reconciliation completion |
| proposal POST failure: non-2xx, invalid JSON, or `ok!==true` | no duplicate POST; schedule exactly one immediate post-action reconciliation cycle | retain row/focus and adjacent alert before the cycle; reconcile only that cycle | idle; schedule 5000ms after reconciliation completion |
| proposal activation / refresh cycle running | set busy synchronously, invalidate that cycle's commit generation, queue the POST until its current GET settles, dispatch no later GET, then start exactly one POST; set `dirty=true` | discard the settling GET; busy row is the only commit | POST owns the sole fetch; after it settles, consume exactly one reconciliation according to visibility |
| document becomes hidden / proposal POST running | do not abort POST; clear timer; remember action result without DOM commit | no announcement/row commit while hidden | remain hidden; visible resumes with exactly one reconciliation |
| proposal POST completes while hidden | no GET and no DOM commit | retain pending success/failure result internally | on visible publish the retained outcome once; success runs one four-GET reconciliation first and then resolves/focuses next, previous, or heading from reconciled DOM; failure restores original action focus and alert before one reconciliation and preserves them through it |
| intermediate sequential GET fails | stop dispatching later GETs; no endpoint after the failure is requested | normally discard partial data and retain all last-good rows; sole exception: if `/api/status` succeeded with `skills_error:"unavailable"` and the later `/api/skills` request fails, commit that status snapshot so Runtime Skills becomes `Unavailable`, retain the last-good Skills rows, and show one Skills alert; background timer does not announce `Updating...` | clear `runningCycle`; consume one pre-existing dirty flag if visible, otherwise retry after 5000ms |
| cycle starts with `dirty=true` | clear dirty before dispatch; issue one cycle only | normal signature reconcile | a trigger during this cycle may set dirty once for one later cycle |
| background timer starts unchanged cycle | sequential GETs | do not set or announce `Updating...`; unchanged commit is silent | schedule normally |
| focused row unchanged/reordered | normal cycle | reuse exact DOM node; preserve active element, selection and list scroll | normal schedule |
| focused row absent in response | normal cycle | mark `data-deferred-remove=true`, retain until focus leaves | on `focusout`, remove then focus next/previous/heading |
| unchanged signatures | normal cycle | zero resource-row mutations and zero live-region announcement | normal schedule |

Priority is absolute: `hidden > action > pre-existing dirty > normal timer`. One event chain may yield at most one immediate reconciliation cycle. Canonical signatures are `JSON.stringify` over normalized arrays in received order and the mapped status fields above. Stable keys are proposal/job/run `id` and skill `name`. The executable reference is `STATE_ROOT\.omo\teams\team-ae9e376f\artifacts\refresh-strategy-harness.js`; W0-T2 extends it into exactly these eighteen deterministic cases, all run in RED, GREEN, and REPLAY:

| ID | Initial state / clocked events | Exact requests and responses | Required terminal DOM/focus/state |
| --- | --- | --- | --- |
| `initial_visible` | visible idle at t0; call start | five successful GETs in strict order | changed rows commit once; cycle/fetch maxima 1; timer due completion+5000 |
| `timer_unchanged` | last-good loaded; advance to timer | same four steady payloads; no Skills GET | zero row/live mutations; focus/scroll unchanged; next timer completion+5000 |
| `timer_changed` | idle; change only jobs payload; advance timer | four steady success payloads; no Skills GET | only Jobs signature/rows change; selection stable |
| `trigger_during_cycle` | begin a steady cycle, pause status response; fire three refresh triggers | one status request, no extra request until it settles; remaining three GETs then one coalesced four-GET cycle | exactly two cycles total; dirty boolean consumed once |
| `hidden_idle` | idle; visibility hidden before timer | no request for 6000ms | text `Paused while hidden`; zero DOM commits; owned timer absent |
| `hidden_during_cycle` | pause approvals GET then hide | status+approvals only until response; no later GET | settling cycle commits nothing; zero hidden commits/requests |
| `visible_resume` | begin from hidden after a successful initial load; make visible | one strict four-GET steady cycle | one newest commit; no replay of hidden response; focus stable |
| `fetch_error_recovery` | visible idle; first steady cycle jobs 503; advance retry 5000 | status, approvals, jobs only; next cycle four steady successes | last-good retained plus one Jobs alert, then alert clears on recovery |
| `focused_reorder` | focus proposal B; server returns C,B,A | four steady success GETs | exact B node identity/focus and scroll retained; visual order updates |
| `focused_remove` | focus proposal B; server omits B | four steady success GETs | B marked deferred until focusout; then next row, previous row, or heading |
| `post_success` | idle; activate Reject once | one POST success then one strict four-GET reconciliation | exact busy/success strings; one POST; mobile list transition before next/previous/heading focus |
| `post_failure` | idle; run 503, invalid JSON, and ok-false subcases with fixture reset | one POST per subcase then one strict four-GET reconciliation | row and action focus retained; one adjacent alert; no duplicate announcement |
| `post_during_cycle` | pause current steady GET; activate action | no later GET; paused GET settles/discards; one POST; one four-GET reconciliation | busy is sole interim commit; maxima 1; no stale generation commit |
| `hidden_during_post` | pause POST; hide before response | one POST; no GET while hidden | no hidden commit/announcement; result retained |
| `post_completes_hidden` | hidden POST resolves success then failure in isolated subcases; show tab | no hidden GET; on visible one four-GET reconciliation per subcase | retained outcome announced once; success reconciles before final focus, failure restores focus/alert before reconciliation; no duplicate change |
| `intermediate_get_failure` | status success; make each later GET fail in separate subcase | stop at failed endpoint; after a Skills failure the next visible retry is five GETs, while every other recovery is four | no later endpoint; partial discard except status+skills-unavailable special case; one alert; a successful Skills retry clears the flag and later cycles return to four |
| `preexisting_dirty_consumption` | set dirty before starting a steady cycle; trigger once more during it | one four-GET cycle plus exactly one later four-GET cycle | dirty clears at start and can be set once; no third cycle |
| `background_updating_silent` | unchanged timer cycle while no user trigger | four steady success GETs; no Skills GET | `Updating...` never announced; zero live-region mutation; normal schedule |

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
uses native browser APIs and inline SVG only so the WebUI adds no frontend
runtime dependency. Advanced filtering, sortable columns, charts, theming, chat, files,
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
- **Dependencies**: `openai[realtime,voice_helpers]` for GPT STT/TTS and
  microphone/speaker I/O; standard library elsewhere. `pytest`/`pytest-cov`
  live in the default uv dev group.
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
- Provider-level subagent event adapters if Claude/Codex CLI surfaces expose a
  stable lifecycle beyond the current generic long-work heartbeat.
- Test suite expansion toward the previous project's coverage bar.

See [DECISIONS.md](./DECISIONS.md) for the rationale behind these choices.
