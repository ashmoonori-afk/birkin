# birkin — Decision Log (ADRs)

Lightweight architecture decision records. Each entry: context, decision,
rationale, alternatives considered, status. Newest decisions may supersede
older ones (noted inline).

> Last updated: 2026-05-27

---

## ADR-001 — Rebuild as a lightweight, zero-dependency core

**Context.** The previous birkin (v0.8) was ambitious: a 65-node workflow graph
engine, FastAPI gateway with 66 endpoints, 9 LLM providers, 724+ tests. The new
goal is explicitly "as lightweight as possible," CLI-first, single-command.

**Decision.** Rebuild from scratch with a minimal core. Preserve the **memory
system** (per owner instruction) but overhaul everything else.

**Rationale.** A small surface is easier to run anywhere, reason about, and let
the agent self-modify. It matches the "Minimal surface" principle.

**Alternatives.** Refactor the existing codebase in place — rejected; the owner
authorized a full overhaul and the new direction diverges substantially.

**Status.** Accepted.

---

## ADR-002 — Python, standard library only

**Context.** Need cross-platform (macOS/Linux/Windows), single-command,
lightweight. hermes is Python; openclaw is Node.

**Decision.** Python ≥ 3.10, **no runtime dependencies** — stdlib only
(`urllib`, `http.server`, `sqlite3` if needed, `argparse`, `html.parser`,
`threading`).

**Rationale.** The owner chose Python (`스택은 python으로`). Stdlib-only means
trivial install, no dependency drift, and easy self-modification. `urllib`
handles the LLM HTTP/SSE; `http.server` handles the dashboard.

**Alternatives.**
- Node/TypeScript (matches openclaw, JS workspace) — rejected after the owner
  selected Python.
- Python with `httpx`/`fastapi`/`pyyaml` — rejected to keep zero-dependency;
  we hand-roll a tiny frontmatter parser and use `urllib`.

**Status.** Accepted (supersedes the initial Node/JS assumption).

---

## ADR-003 — Canonical message format = Anthropic content blocks

**Context.** Need a provider-agnostic internal representation for messages,
tool calls, and tool results.

**Decision.** Use Anthropic's content-block shape as the canonical format; the
OpenAI provider adapts to/from it.

**Rationale.** Anthropic is the default provider; tool_use/tool_result blocks
map cleanly and support streaming. One native path + one adapter is simpler
than a third neutral format.

**Alternatives.** A bespoke neutral schema — more code, more mapping, no gain
while Anthropic is the default.

**Status.** Accepted.

---

## ADR-004 — Skills use the `SKILL.md` (agentskills.io / hermes) standard

**Context.** Must reflect hermes' skills system and openclaw's skillsets, and
keep skills portable.

**Decision.** A skill is a directory with a `SKILL.md` (YAML frontmatter +
markdown body). Grounded on the *actual* installed hermes format
(`name`, `description`, `version`, `metadata.hermes.tags`, `When to Use`).
Discovery merges bundled + user dirs; user shadows bundled.

**Rationale.** Portability with the broader ecosystem; verified against the
real installed hermes skills rather than guessed.

**Alternatives.** A custom skill format — rejected; breaks portability.

**Status.** Accepted.

---

## ADR-005 — Progressive disclosure for skills and memory

**Context.** Injecting every skill/note into the prompt is wasteful and noisy.

**Decision.** The system prompt carries only a compact **index** (one line
each). The agent calls `load_skill` / `memory_get_note` / `memory_search` to
pull full content on demand.

**Rationale.** Keeps context small and cost low while scaling to many
skills/notes. Same pattern hermes uses.

**Status.** Accepted.

---

## ADR-006 — Memory is an Obsidian vault ("compile over retrieve")

**Context.** Owner instruction: keep the previous memory system; **using an
Obsidian vault for semantic memory is mandatory**.

**Decision.** Store memory as a directory of Obsidian-compatible markdown notes
with YAML frontmatter and `[[wikilinks]]`. Compile conversations/files into
notes (entities, classification, links) rather than embedding into a vector
store. Keyword search over the vault for v0.1.

**Rationale.** Matches the mandate and the "Compile over retrieve / Transparent"
principles. The vault is human-inspectable and editable in Obsidian. Stdlib
keyword search avoids an embeddings dependency.

**Alternatives.**
- Vector DB / embeddings — deferred to an optional upgrade (ADR-roadmap);
  conflicts with zero-dependency and "compile over retrieve."
- Single JSON memory file — insufficient for a semantic, linked, Obsidian
  vault; superseded.

**Status.** Accepted. Supersedes the initial JSON-file memory implementation.

---

## ADR-007 — Self-improvement is a scheduled nightly routine with an approval gate

**Context.** Owner definition of "self-improving": at **04:00 daily**, review
the last 24h of conversation and added files; improve the next day; author
skills; set up cron jobs; **get user approval before executing** consequential
actions.

**Decision.**
- A portable daemon (`birkin daemon`) wakes at `nightly_hour` (default 4) and
  runs `nightly.py`; it also runs due cron jobs.
- The nightly "night agent" **applies safe changes directly** (memory compile,
  skill authoring) but only **proposes** consequential actions (cron jobs,
  command execution) into a pending-approval queue.
- `birkin review` / the dashboard let the user approve/reject; only approved
  actions execute.

**Rationale.** Delivers autonomy while honoring "Transparent" and
"Human-in-the-loop." Separating *safe/auto* from *consequential/approved* keeps
trust without blocking useful self-improvement.

**Alternatives.**
- Fully autonomous execution — rejected; unsafe and against the explicit
  approval requirement.
- Approval for *everything* (incl. memory/skills) — rejected as too noisy;
  vault notes and skills are reversible and low-risk.

**Status.** Accepted.

---

## ADR-008 — Portable Python scheduler instead of OS cron

**Context.** Need scheduling on macOS/Linux/Windows without per-OS setup.

**Decision.** Implement scheduling as a long-running Python daemon loop. Offer
optional OS-native registration (`crontab`/`schtasks`) later as opt-in.

**Rationale.** One cross-platform implementation; no privileged setup required
to try it. Cron syntax differs across OSes and Windows has no native cron.

**Trade-off.** The daemon must be running to fire jobs; it does not survive
reboots by itself (mitigated by future opt-in OS registration).

**Status.** Accepted.

---

## ADR-009 — WebUI is a monitoring dashboard, not a chat client

**Context.** Owner clarification: the WebUI should show running jobs and result
summaries — it is a dashboard, not a chat.

**Decision.** The WebUI is read-mostly: status, scheduled/running jobs, recent
run summaries, and pending approvals (approve/reject). Chat stays in the CLI
REPL (`birkin chat`).

**Rationale.** Clear separation of concerns: terminal for interaction, browser
for observability and approvals. Smaller WebUI surface.

**Alternatives.** A 10-tab WebUI like the previous project — rejected as too
heavy for the lightweight goal.

**Status.** Accepted. Supersedes the initial streaming-chat WebUI prototype
(which is being reworked into the dashboard).

---

## ADR-011 — Add a lightweight gateway + onboarding (hermes-parity)

**Context.** Owner asked for an execution sequence identical to hermes: a
`setup` onboarding wizard and a `gateway`. The original non-goals (ADR-001)
excluded a multi-channel gateway.

**Decision.** Add a small **gateway control plane** (`birkin gateway`) with a
pluggable channel registry: a localhost **HTTP** channel by default and an
optional **Telegram** channel (stdlib long-polling). One shared session store
(memory + skills) backs every channel, with per-(channel, chat) history. Add a
guided **onboarding wizard** (`birkin setup`/`onboard`) that also runs on first
launch, plus `birkin tools` to enable/disable tools (hermes parity).

**Rationale.** Satisfies the explicit request while staying stdlib-only: HTTP
via `http.server`, Telegram via `urllib`. Channels are pluggable so more can be
added without touching the core. Revises ADR-001's gateway non-goal — but stays
far lighter than openclaw's 20+ channel gateway.

**Alternatives.** Full multi-platform gateway (Slack/Discord/WhatsApp/…) —
deferred; each is an opt-in channel module to add later.

**Status.** Accepted (partially supersedes the gateway non-goal in ADR-001).

---

## ADR-012 — Local CLI agents (Claude Code / Codex) as model backends

**Context.** Owner: birkin must run on the **installed `claude` (Claude Code)
and `codex` CLIs**, like hermes — using their own logins instead of an API key.

**Decision.** Add `claude-cli` and `codex-cli` providers. `models.discover`
detects the CLIs via `shutil.which` and lists them in the picker alongside API
and Ollama models. `LLMClient` shells out non-interactively
(`claude -p --output-format json [--model]`, `codex exec [-m]`), flattening the
conversation into the prompt and returning the reply as assistant text. No API
key needed (`get_api_key` returns a `"cli"` sentinel); birkin is a thin proxy
and does not run its own tool loop in this mode (the CLI agent runs its tools).

**Rationale.** Directly satisfies the requirement and reuses existing Claude
Code / Codex subscriptions. Stdlib-only (`subprocess`). Verified end-to-end:
`claude -p` returns `{"result": ...}` which birkin parses.

**Trade-off.** In CLI mode birkin's own tools aren't invoked as structured tool
calls. API providers remain the path for the native tool-calling loop.

**Update (ADR-014).** CLI mode is no longer a bare proxy: birkin now injects a
concise CLI system prompt with its **identity, memory digest, and the skills
routed to the request** (full text + bundled-script paths) so CLI agents answer
as birkin, use memory, and follow/execute skills with their own tools. See
ADR-014.

**Status.** Accepted.

---

## ADR-013 — Automatic skill-ization via nudges (copied from hermes)

**Context.** Owner: replicate hermes' automatic skill creation — the agent
"creates skills from experience" and "nudges itself to persist knowledge."

**Decision.** Copy hermes' nudge mechanism in the agent loop (no extra LLM
call): count tool-calling iterations; if a turn does substantial tool work
(`skill_nudge_interval`, default 3) without calling a skill tool, queue an
**ephemeral** note for the next turn suggesting `create_skill` / `improve_skill`.
A turn-based counter (`memory_nudge_interval`, default 6) does the same for
`remember` / `memory_write_note`. Counters reset when the relevant tool is used.
Nudges are added to the system prompt for one turn only and never stored in
history. Both intervals are configurable; `0` disables.

**Rationale.** Faithful to hermes (turn/iteration counters, ephemeral
injection, reset-on-use) and cheap — it steers the model to self-author skills
instead of running a separate reflection pass on every turn. The `/learn`
command and the nightly routine remain for explicit/batch consolidation; a
background "curator" (hermes' skill maintenance) is possible future work.

**Status.** Accepted.

---

## ADR-014 — Skills & memory work in CLI-agent mode via prompt injection

**Context.** Owner: hermes uses skills even on CLI agents — make birkin do the
same instead of treating CLI mode as a bare proxy (which also made the CLI act
like a translator, since no system prompt was sent).

**Decision.** For CLI providers, build a concise **CLI system prompt**
(`prompts.build_cli_system`) and send it with the conversation:
- birkin identity + "act, don't describe; answer in compact Markdown",
- a **memory digest** (`memory.render()`),
- the **skills routed to the request** (`SkillManager.route()` — keyword overlap
  on name/description/tags/body, top 3), rendered full-text via
  `render_skill()` including the skill's directory and bundled-script paths.

The CLI agent (Claude Code / Codex) then answers as birkin, uses the injected
memory, and follows/executes the skills with its own shell. The tool-oriented
guidance (`load_skill`, `spawn_subagent`) is omitted in CLI mode to avoid
confusion.

**Rationale.** Gives the hermes outcome (skills everywhere) without a
text-protocol tool loop over a completion backend. Routing keeps the prompt
small; bundled-script paths make skills executable in CLI mode too.

**Trade-off.** Skills are pre-selected by keyword routing rather than pulled on
demand; the CLI agent can't write back to birkin memory/skills within the turn
(captured later by `/learn` or the nightly routine).

**Status.** Accepted (refines ADR-012).

---

## ADR-015 — Per-turn run records + ledger + usage estimate (auditability)

**Context.** Improvement plan Phase 2 (idea from birkin_codex): make every turn
auditable.

**Decision.** Each chat/agent turn writes a JSON **run record** to
`~/.birkin/runs/` (provider, model, tools used, iterations, summary, usage) and
appends a compact line to `~/.birkin/ledger.jsonl`. `store.estimate_usage`
provides a transparent heuristic (chars/words/≈tokens = chars/4). Run ids carry
a short uuid suffix to avoid same-second collisions. `Session._record_turn`
captures this from `agent.last_tools` / `last_iterations`; `birkin runs` and the
dashboard surface it. `save_run` (also used by nightly/cron) now ledgers too.

**Rationale.** Cheap, dependency-free auditing + cost sense without a real
token API. Reuses the existing `store` + dashboard plumbing.

**Trade-off.** A file per turn accumulates in `runs/`; usage is an estimate, not
provider-reported. Pruning/retention can be added later.

**Status.** Accepted.

---

## ADR-016 — Config-driven local-cli runner + dry-run/packet mode

**Context.** Improvement plan Phase 3: reduce hardcoded provider dispatch and
add a cost-free way to inspect the prompt.

**Decision.** (a) Add a generic **`local-cli`** provider: `config.cli_command`
(argv) runs with the flattened prompt on stdin (via `proc.cli_argv`), stdout is
the reply — any local agent/model can be a backend without code. It joins the
existing providers; the native Anthropic tool-calling loop is unchanged and
remains the path for `anthropic`. (b) Add **`birkin chat --dry-run`** backed by
`runtime.build_dry_run_packet`, which assembles the exact system prompt + tool
names (or routed skills for CLI providers) + usage estimate **without a client
or API key**.

**Rationale.** Most of codex's config-driven-runner benefit (pluggable CLIs) and
its "packet" transparency, with minimal surface, no regression to the agentic
loop, and no new dependency.

**Trade-off.** Not a full multi-profile registry — a single active provider +
`cli_command`. A profiles map can be layered later.

**Status.** Accepted (extends ADR-003 / ADR-012).

---

## ADR-017 — Skill freshness: hot-reload, gating, sync, layered prompts

**Context.** Improvement plan Phase 4: keep the skill catalog fresh, scalable,
and context-appropriate (codex ideas: watch, eligibility, upstream mirror,
SOUL/AGENTS/TOOLS).

**Decision.**
- **Hot-reload**: `SkillManager.reload_if_changed()` compares a cheap mtime
  signature (stat only, debounced) and re-discovers on change; called before
  each turn so edited/added skills land without a restart.
- **Gating**: `Skill.eligible` checks frontmatter `prerequisites.commands`
  (via `shutil.which`) and `prerequisites.platforms`; `index()`/`route()` show
  only eligible skills, while `get()`/`load_skill` can still load by name.
- **Sync**: `birkin skills sync` (`skills/sync.py`) mirrors an upstream skill
  tree (auto-detected hermes, or `--from`) into `~/.birkin/skills/mirrors/`,
  preserving bundled scripts and appending a source-attribution line.
- **Layered prompts**: `prompts.workspace_prompt_block()` composes `SOUL.md` /
  `AGENTS.md` / `TOOLS.md` from the cwd into the system prompt when present.

**Rationale.** Matches codex's freshness/scale features with stdlib-only,
low-risk additions; gating prevents recommending skills that can't run here;
sync grows the catalog on demand without bloating the shipped package.

**Trade-off.** Hot-reload polls mtimes (no OS file-watch dependency); sync
mirrors verbatim (upstream license/attribution preserved, not transformed).

**Status.** Accepted.

---

## ADR-018 — Live-LLM verification harness (opt-in marker)

**Context.** Hardening Phase H2: the real agentic loop (Anthropic tool_use,
multi-turn, subagent) was only logic-verified by P1 fakes/monkeypatch — no
real-backend smoke in CI.

**Decision.** Add a `live` pytest marker; offline runs deselect it via
`addopts = "… -m 'not live'"`. Live tests skip themselves unless
`BIRKIN_LIVE=1` is set and a backend is available (`ANTHROPIC_API_KEY`, or the
`claude` / `codex` CLI on PATH). Cases:
- chat turn returns non-empty reply,
- chat-with-tool-or-useful-reply (asserts a tool was actually called when the
  native API loop is the backend; relaxed to "useful reply" for CLI proxies),
- subagent round-trip (skipped for CLI proxies, where no native subagent loop runs).
`scripts/smoke_live.{sh,ps1}` wraps the run.

**Rationale.** Closes the biggest v0.1 risk (unverified live paths) cheaply —
short prompts on Haiku-grade or CLI quota — without making offline CI
key-dependent. Easy to extend with more cases.

**Status.** Accepted.

---

## ADR-020 — Verified learning: Skill-PR mode + memory TTL

**Context.** Hardening Phase H4: the v0.1 review flagged two concrete risks —
(a) automatic skill writes had no audit trail (a paste of birkin_codex's
"+25 dealbreaker" complaint), and (b) "learned" avoidances were stored as
permanent skill text even when they were transient environment problems.

**Decision.**
- **Skill-PR mode.** `create_skill` and `improve_skill` no longer write the
  user-skills tree directly; they call `approvals.propose(category="skill", …)`
  with the full proposal payload. With the matching category in
  `auto_approve` (default) the proposal applies immediately; otherwise it
  queues in `pending/` and is applied by `birkin review`. Either way there is
  always a pending record. `manager.apply_skill_proposal(payload)` is the
  single writer; `improve_skill` forks bundled skills into the user dir
  instead of mutating them in place. Side effect: `auto_approve` default fixed
  from `["memory","skills"]` (the second was a no-op) to `["memory","skill"]`.
- **Memory TTL.** A note can declare an `expires_at` ISO date in frontmatter
  (`memory_write_note` exposes `ttl_days`). Expired notes are excluded from
  `list_notes`, `search`, and `render` (the prompt digest / router) so the
  agent stops seeing them. `get_note` still returns them by name for audit.

**Rationale.** Closes "no skill mutated without a recorded proposal" + "a
'learned' avoidance re-verifies before reuse" from the v0.1 review with the
minimum machinery. Reuses the existing approval/run-record audit plumbing —
no new subsystem.

**Trade-off.** Auto-approve keeps the agent fast by default (no friction in
the hot path); to require manual review, drop `skill` from `auto_approve`.
TTL is implemented as a hard filter (no gradual decay yet); negative-memory
typing arrives in H5.

**Status.** Accepted.

---

## ADR-019 — Reliability control plane: SIGTERM, stale heartbeat, budget, trace

**Context.** Hardening Phase H3: a hard kill could leave the dashboard
claiming a dead daemon was running, and there was no cost gate — silent failure
in either direction.

**Decision.**
- `scheduler.run_daemon` installs `atexit` and `SIGTERM` handlers that call
  `store.clear_status()`. `signal.signal` is wrapped in try/except for
  platforms / contexts where setting handlers isn't allowed.
- `store.is_status_stale(status, max_age_seconds=120)` decides whether a
  heartbeat is too old to trust; `/api/status` returns `stale` and forces
  `daemon: false` accordingly, so a crashed daemon never shows running.
- New `birkin/budget.py` sums `estTokens` from the run ledger over a window
  and reports / gates spending. `Session.ask` short-circuits over-budget turns
  with a clear message and writes a `skipped: over-budget` run record — no LLM
  call, no silent spend. `birkin budget` shows usage vs caps; dashboard surfaces
  the same. Defaults `0 = unlimited` so behavior is opt-in.
- `birkin trace <run-id>` prints a single run record (audit replay).

**Rationale.** Cheap, transparent reliability primitives — no daemon
supervisor, no metrics backend; just the heartbeat we already had + the run
ledger we already keep. Doesn't disturb the agentic loop or stdlib-only runtime.

**Trade-off.** Budget uses `estTokens` (chars / 4 heuristic), not exact
provider-reported cost; stale heartbeat is a fixed 120 s threshold; budget gate
is hard-stop (no soft warning yet). All adjustable in config / future ADRs.

**Status.** Accepted.

---

## ADR-010 — Single shared session, sequential dashboard server

**Context.** Local, single-user tool.

**Decision.** Use a plain (sequential) `HTTPServer` with one shared `Session`,
guarded by a lock. No async framework.

**Rationale.** A single local user does not need concurrency; sequential
handling avoids races on the shared agent/session and keeps the code tiny.

**Status.** Accepted.
