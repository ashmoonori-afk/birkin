# birkin — Hardening Plan (closing the v0.1 weaknesses)

> Created 2026-05-28. Targets the gaps from the v0.1 review: unverified live-LLM
> paths, thin coverage on I/O modules, daemon robustness, CLI-proxy fidelity,
> and skill-quality variance. Goal of this plan: reach a **trustworthy beta**.

## Guardrails (unchanged)

- Do **not** regress: native agentic loop, interactive UX, LLM self-improvement,
  argv-only subprocess, the run-record/ledger audit, config-driven runners.
- **Runtime stays stdlib-only.** Test/coverage tooling (`pytest`, `coverage`)
  is **dev-only** and must never be imported by `birkin/`.
- Per phase: verification-loop → code review (spaghetti / consistency / security
  / progress) → update `docs/STATUS.md` (+ ADR if a decision) → commit & push.
- Offline CI must stay green with **no API key**; live checks are opt-in.

---

## Phase H1 — Test depth & coverage (highest priority)

**Why:** 57 tests exist but I/O-heavy modules (web, gateway, scheduler, repl,
onboarding, cli handlers, llm adapters) are barely covered; coverage is unmeasured.

**Do:**
- Add `coverage` (or `pytest-cov`) to the `dev` extra; add a `coverage` config;
  produce a term-missing report.
- New offline tests (fakes/monkeypatch, no network):
  - **llm**: `_to_openai_messages` mapping; `_post` retry/backoff (monkeypatch
    `urlopen` to raise then succeed); Anthropic payload shape incl. `cache_control`
    (monkeypatch `_post` to capture the payload); OpenAI `complete` parsing.
  - **agent**: max-turns guard message; tool-error result still feeds the loop;
    multiple tool_uses in one turn.
  - **runtime**: `build_session` raises `ConfigError` without a key; `_record_turn`
    writes a record; `_build_cli_system` injects identity+memory+routed skills.
  - **web/server**: start `HTTPServer` on port 0 in a thread; assert `/`,
    `/api/status|skills|runs`, POST `/api/approvals` token + Host 403/200.
  - **gateway**: `Gateway.handle` routes per (channel, chat) with a fake session;
    `/new` resets; `LocalHTTPChannel` `/health` + `/message` + forged-Host 403.
  - **scheduler**: `_next_nightly`; due-job firing; `_run_job` shell via monkeypatch.
  - **cli**: `build_parser` accepts every subcommand; `_cmd_runs/_cmd_tools/
    _cmd_permission/_cmd_cron` with fakes.

**Accept:** coverage report emitted; **≥ 75% overall**, and web/gateway/scheduler/
cli/llm each have direct tests; offline, key-free, green.

---

## Phase H2 — Live-LLM verification harness (close the biggest risk)

**Why:** the real agentic loop (Anthropic tool_use, multi-turn, subagent,
nightly) is only logic-verified, not exercised against a real model.

**Do:**
- A `@pytest.mark.live` suite, **skipped unless `BIRKIN_LIVE=1`** and a backend is
  available (API key or installed `claude`/`codex`). Cases:
  - one chat turn that must call a tool (e.g. "list the files here, then say how
    many") → assert a tool ran and a non-empty reply came back;
  - a `spawn_subagent` round-trip;
  - `birkin nightly --dry-run`-style assembly with a real summarize call (cheap).
- A `scripts/smoke_live.(sh|ps1)` one-shot that runs the above and prints a PASS/
  FAIL line; documented in README/STATUS.
- Keep costs tiny (short prompts, Haiku/sonnet or the CLI agent).

**Accept:** `BIRKIN_LIVE=1 pytest -m live` passes with a real backend; offline
`pytest` still ignores live tests; documented how to run.

---

## Phase H3 — Daemon & scheduler robustness

**Why:** a hard kill (SIGTERM) leaves a stale `daemon: true`; long-run untested.

**Do:**
- Handle `SIGTERM` (and `atexit`) to `store.clear_status()`.
- Treat a **stale heartbeat** (> ~2 min) as "stopped" in `read_status` consumers
  (dashboard + `birkin` status), so a dead daemon never shows as running.
- Tests: stale-heartbeat detection; next-nightly rollover; due-job dedupe per day.

**Accept:** after SIGTERM the status is cleared or shown stopped; tests cover the
stale-heartbeat path.

---

## Phase H4 — CLI-proxy fidelity & skill quality

**Why:** in CLI-agent mode skills are injected as the top-3 routed texts (less
precise than on-demand `load_skill`); 48 skills were largely subagent-authored.

**Do:**
- Make the routed-skill budget configurable (`cli_skill_budget`, default 3) and
  allow **pinning** a skill for the next turn (e.g. `/use <skill>` injects it).
- `birkin skills validate`: lint every `SKILL.md` (required `name`/`description`,
  parseable frontmatter, has `When to Use` / `When NOT to Use`, bundled `*.py`
  compiles via `py_compile`); non-zero exit on problems.
- Run `skills validate`, fix flagged skills, and curate/trim weak ones.

**Accept:** `birkin skills validate` reports and exits non-zero on malformed
skills; the shipped catalog passes; routed budget configurable + pin works.

---

## Sequencing

H1 → H2 → H3 → H4 (H1+H2 close the biggest risk first). Each phase is
independently shippable; stop after H4 or when redirected. No unrelated refactors.
A successful run lifts birkin from "strong v0.1" to "trustworthy beta (v0.2)".
