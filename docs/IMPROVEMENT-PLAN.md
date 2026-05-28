# birkin — Improvement Plan (porting the good parts from birkin_codex)

> Created 2026-05-28. Source of ideas: the codex-built `birkin_codex` workspace.
> Goal: adopt its strongest engineering ideas **without** regressing birkin's
> advantages — the real agentic tool-calling loop, the interactive chat UX, and
> LLM-driven self-improvement.

## Guardrails (do not regress)

- Keep the **native agentic loop** (Anthropic `tool_use`, multi-turn, birkin runs
  the tools). This is birkin's core edge over the packet/single-shot design.
- Keep the **interactive UX** (streaming/spinner, Markdown rendering, arrow-key
  menus, slash commands) and **LLM self-improvement** (nudges, `/learn`, nightly).
- Stay **stdlib-only at runtime** (pytest is a dev-only extra).
- Work in the canonical clone `C:\Users\lg\Documents\Claude\Projects\Birkin\birkin`
  (editable-installed). Commit + push to `main` per phase; old v0.8 stays on
  `legacy-v0.8`.
- After each phase: run the verification-loop + a code review (spaghetti,
  consistency, security, progress), update `docs/STATUS.md`, add an ADR when a
  decision is made. Never claim done without running the checks.

---

## Phase 1 — Safety & tests (highest ROI)

**1.1 argv subprocess (remove `shell=True`).**
Replace every `subprocess.run(..., shell=True)` with an **argv list** and pass
input via stdin. Files: `tools/shell.py`, `approvals.py`, `scheduler.py`
(`_run_job`, OS install), `llm.py` (`_run_claude`/`_run_codex`),
`slashcommands.py` (`/update`). For the `run_shell` tool (which legitimately runs
user shell), keep shell semantics but via an explicit shell argv
(`["bash","-lc",cmd]` / `["cmd","/c",cmd]`) chosen by platform, documented as the
one intentional exception.
- *Accept:* `grep -rn "shell=True"` shows only the documented run_shell case;
  commands still work on Windows + POSIX.

**1.2 pytest suite (birkin has zero tests).**
Add `tests/` covering: `skills/frontmatter` (incl. hermes nested tags),
`memory` vault (write/search/links/render), `skills.route`/`render_skill`,
`approvals` (auto vs queue → approve → cron), `store`, `cron.due_jobs`,
`llm._read_anthropic_stream` (parallel tool_use), and the `agent` loop with a
fake client (incl. the skill/memory nudge trigger). Add `pytest` to
`[project.optional-dependencies].dev`.
- *Accept:* `pytest` green; ≥ ~25 tests; runs with no network/API key.

---

## Phase 2 — Auditability (run records + ledger + usage)

**2.1 Per-turn run records.** Every chat/agent turn writes a JSON record to
`~/.birkin/runs/` (timestamp, provider/model, tools used, prompt size, est.
tokens, status, short summary). Reuse/extend `store.save_run`.
**2.2 Ledger.** Append a one-line entry per run to `~/.birkin/ledger.jsonl`.
**2.3 Usage estimate.** A small helper (chars/words/≈tokens = chars/4) recorded
on each run; show totals in the dashboard and a `birkin runs` command.
- *Accept:* a chat turn produces a run record + ledger line; `birkin runs` lists
  recent runs with usage; dashboard shows them.

---

## Phase 3 — Config-driven runners + dry-run

**3.1 Runner/model profiles in config.** Generalize the hardcoded provider
dispatch into profiles in `~/.birkin/config.json`:
`{provider, model, runner: "anthropic"|"openai"|"local-cli"|"packet", command:
[argv...], timeout}`. Keep the **native Anthropic loop** as the `anthropic`
runner; `local-cli` runs a configured argv (codex/claude/anything); `openai` as
today. Validate profiles (`birkin model` / a `doctor` check).
**3.2 dry-run / packet mode.** `birkin chat --dry-run` (and a `/dry` toggle)
builds and prints the full system prompt + tool list + routed skills **without
any model call** (mirrors codex's "packet"). Useful for debugging/cost-free
inspection.
- *Accept:* a new CLI/API runner can be added via config only (no code change);
  `--dry-run` makes zero network calls and prints the packet.

---

## Phase 4 — Skill scale & freshness

**4.1 Hot-reload (watch).** Reload skills when a `SKILL.md` changes (mtime poll
with debounce; no extra deps) so edits land without restarting.
**4.2 Upstream sync tool.** `birkin skills sync` mirrors selected hermes/openclaw
skills into `~/.birkin/skills/` (or a `mirrors/` dir), preserving attribution and
bundled scripts (stdlib-only ones).
**4.3 Eligibility/gating.** Optional `prerequisites` in frontmatter (commands /
platform); gated skills are hidden from the index/router when prereqs are absent.
**4.4 Grow the catalog.** Port more hermes-style skills in parallel (subagents),
prioritizing stdlib-runnable bundled scripts.
- *Accept:* editing a skill reloads live; `birkin skills sync` adds mirrors;
  a gated skill disappears when its command is missing; catalog noticeably larger.

**4.5 Layered prompt files (optional).** If `SOUL.md` / `AGENTS.md` / `TOOLS.md`
exist in the workspace, compose them into the system prompt (identity/policy),
and emit the skill catalog in a compact, location-bearing form.
- *Accept:* present files are composed in; absent files are ignored.

---

## Sequencing & exit

Do phases in order (1 → 4); each phase is independently shippable. Phase 1 is the
priority. Stop after Phase 4 (or earlier if the user redirects). Do **not** start
unrelated refactors. Keep every change small, verified, and committed per phase.
