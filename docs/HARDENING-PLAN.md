# birkin — Hardening & Spinoff Roadmap

> Updated 2026-05-28. Incorporates the v0.1 review **and** the Hermes
> strengths/weaknesses strategic analysis. Goal: lift birkin from "strong v0.1"
> to a **trustworthy beta** and a differentiated spinoff.

## Positioning

**"성장하지만 — 검증되고, 안 죽고, 허락받는 에이전트."**
(An agent that grows with you, but is *verified*, *always-on-reliable*, and
*approval-respecting*.)

The durable moats, in order of how hard they are to copy:
1. **Local-trust + data/memory flywheel** (hardest to copy; accrues per user).
2. **Reliability control plane** (turns a toy into something you leave running).
3. **Verified self-improvement** (Hermes can't easily add learning friction —
   it conflicts with their "agent grows with you" identity).

Engineering-rigor moats (#2/#3) are replicable by funded competitors over time;
the **data/trust flywheel (#1)** is the lasting one — so memory reliability,
portability, and trust KPIs are first-class, not afterthoughts.

## Core design principle

**Fast-by-default, rigorous-on-demand.** Verification, approval, and grading
must NOT kill the first-10-minute wow. Default to fast; escalate rigor by risk
tier / config. (birkin already starts this via `auto_approve` + `cli_access`.)

## Trust KPIs (build measurement *into* the product)

"Verified" must be provable, not a slogan. Track and surface:
- learned-helplessness recurrence rate (re-failing a thing we "learned" to avoid),
- mis-saved memory rate (wrong store / contradicted later),
- approval reject rate, silent-failure detection rate,
- $/day and per-task cost (budget governor).

## What birkin already has vs the gaps

| Differentiator | birkin today | Gap to close |
|---|---|---|
| Verified learning | `verification-loop` skill, "verify before claiming", run records/ledger | **2nd-opinion grader, Skill-PR/diff mode, auto-test-before-learn, confidence+TTL** — note: birkin's `create_skill/improve_skill` still overwrite directly (it *shares* the auto-overwrite risk) |
| Memory OS | Obsidian vault w/ `type` + `confidence` + `sources` | ephemeral/TTL, negative memory, versioning/optimistic-lock, multi-device sync |
| Reliability | run records + ledger + usage + dashboard + heartbeat | supervisor, budget governor, alerting, delivery guarantee, replay |
| Approval-first | approval queue + permission tiers + access levels + `chat --dry-run` | signed skills, permission manifest, immutable official skills, `skills validate` |
| Onboarding | arrow-key wizard + Telegram connect | GUI / visual skill builder |
| Asia wedge | — | LINE first, then Kakao/Naver/Toss/HyperCLOVA |

**Implication:** the spinoff is not a rewrite — it's **closing these gaps on top
of birkin** (~30–40% already in place).

## Licensing (dual)

birkin's **original** code and skills move to a **copyright-protective license**
(source-visible, not freely reusable). **Third-party / ported** skills (hermes
mirrors via `skills sync`, the ported `arxiv` skill) **retain their upstream MIT
license + attribution** — we cannot and do not relicense others' work. A root
`LICENSE` + `NOTICE` records the split; per-skill frontmatter `license` reflects
which applies. (Exact protective license: see the open decision below.)

---

## Phases (reordered per the review)

### P1 — Test depth & coverage *(foundation for "verified")*
Add `coverage` (dev-only); offline tests (fakes/monkeypatch) for the thin
modules — `web/server` (thread `HTTPServer`: `/`, `/api/*`, POST token+Host),
`gateway` (`handle` routing, `LocalHTTPChannel`), `scheduler` (`_next_nightly`,
due jobs, `_run_job`), `runtime` (`ConfigError`, `_record_turn`, `_build_cli_system`),
`llm` (OpenAI mapping, `_post` retry, Anthropic payload `cache_control`), `agent`
(max-turns, tool-error, multi tool_use), `cli` (parser + handlers).
**Accept:** report emitted; **≥75% overall**; offline, key-free, green.

### P2 — Live-LLM verification harness *(closes the biggest risk)*
`@pytest.mark.live` (skipped unless `BIRKIN_LIVE=1` + a backend); a real chat
turn that must call a tool, a `spawn_subagent` round-trip, a cheap nightly
summarize. `scripts/smoke_live.*` one-shot. **Accept:** live suite passes with a
real backend; offline `pytest` ignores it.

### P3 — Reliability control plane *(moved up: toy → trusted)*
Process **supervisor** + crash recovery; `SIGTERM`/`atexit` clears status;
**stale heartbeat (>2 min) ⇒ stopped**; **budget governor** (daily/monthly caps,
per-task model routing) surfaced in `birkin runs`/dashboard; **alerting** on
silent failure; gateway **delivery guarantee** (sent-confirmation) + health;
**trace timeline / replay** (user→tool→subagent→delivery). **Accept:** dead
daemon never shows running; over-budget halts with a clear message; a failed
delivery is detected, not silent.

### P4 — Verified learning *(the USP; closes complaint #1/#2/#6)*
**Skill-PR mode** (auto edits become diffs/proposals, never silent overwrite) +
**rollback/blame**; **2nd-opinion grader** (adversarial check before claiming
success); **auto-test-before-learn** (a new skill needs ≥1 reproduction check);
**confidence + TTL** (low-confidence / transient-env lessons are ephemeral and
expire). **Accept:** no skill is mutated without a recorded proposal; a "learned"
avoidance re-verifies before reuse; grader can veto a success claim.

### P5 — Memory OS
Typed/scoped memory with policy (User/Project/Environment/Workflow/Ephemeral/
Negative); **TTL** expiry; **negative memory** ("this failed") with re-verify;
**versioning + optimistic lock** (no stale-snapshot overwrite); evidence-gated
writes. **Accept:** a transient note auto-expires; a stale write is rejected;
every memory has a source.

### P6 — Approval-first & skill integrity
`birkin skills validate` (frontmatter lint, required sections, bundled `*.py`
`py_compile`); **signed skills** (author/version/hash + permission manifest);
**immutable official skills** (fork/PR only); risk-tiered approval inbox; public-
channel human-in-the-loop gate. **Accept:** malformed skills fail validate;
official skills can't be silently patched; risky actions queue for approval.

### GTM track *(product, not hardening — sequence after the trust foundation)*
- **LINE first** (validate demand) → then Kakao/Naver Works/Toss/HyperCLOVA.
  Each Asian connector is heavy (KakaoTalk outbound is business-channel-gated) —
  do **one**, prove demand, expand.
- **GUI / vibe-native onboarding** (hide AGENTS/SOUL/cron behind a wizard).

## Sequencing & exit

P1 → P2 → P3 → P4 → P5 → P6, GTM after the trust foundation. Each phase is
independently shippable: verification-loop → code review → STATUS/ADR → commit &
push. Guardrails unchanged: no regression to the agentic loop / interactive UX /
self-improvement; **runtime stdlib-only** (coverage/pytest dev-only); offline CI
green without a key.

---

## Open decision — protective license

Pick the copyright-protective license for birkin's **original** work (ported MIT
skills are unaffected): **Proprietary / All-Rights-Reserved**, **BUSL-1.1**
(source-available, converts to OSS after a change date), or **PolyForm
Noncommercial** (free for non-commercial; commercial needs a license). Apply to
`pyproject` + root `LICENSE`/`NOTICE` + original skill frontmatter, keeping
mirrored/ported skills MIT with attribution.
