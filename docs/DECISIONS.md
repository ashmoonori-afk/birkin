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

## ADR-010 — Single shared session, sequential dashboard server

**Context.** Local, single-user tool.

**Decision.** Use a plain (sequential) `HTTPServer` with one shared `Session`,
guarded by a lock. No async framework.

**Rationale.** A single local user does not need concurrency; sequential
handling avoids races on the shared agent/session and keeps the code tiny.

**Status.** Accepted.
