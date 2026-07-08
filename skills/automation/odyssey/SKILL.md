---
name: odyssey
description: "Goal-completion cycle — clarify, plan, adversarially critique, then execute one verified step at a time until a complex GOAL is done. On-demand only (NOT every turn)."
version: 0.1.0
author: birkin
license: MIT
metadata:
  birkin:
    tags: [automation, orchestration, goal, planning, verification, ultrawork]
    status: "design v0.1 — skill-as-protocol; dedicated runtime lands per docs/v2.md waves"
    run_param: goal
---

# Odyssey — goal-completion cycle

Drive a **complex GOAL** to a verified finish: clarify it, plan it, let critics
attack the plan, then execute **one step at a time**, checking each step with an
independent verifier (**Osiris**) before moving on — and stop only when the whole
goal is verified. The relentless sibling of one-shot answering; pairs with
`neurosis` (clarify) and `morpheus` (nightly). Label visible progress lines
**`[Odyssey]`** (and verifier lines **`[Osiris]`**).

This is the heavy cycle, so it is **on-demand** — it must NOT run on an ordinary
turn. (Borrowed from oh-my-openagent's `ultrawork`/`$start-work`; see
`docs/v2.md`.)

## When to Use

- A **multi-step goal** that needs planning + verification: "build / migrate /
  refactor / ship X end-to-end", "get the suite green", "wire up feature Y".
- The user types **`ultrawork`** / **`ulw`**, or invokes `/odyssey <goal>` /
  `birkin odyssey "<goal>"`.

## When NOT to Use (run a normal turn instead)

- A question, a quick lookup, a single-file edit, a chat reply. These are plain
  turns — Odyssey would be wasteful overkill. Just do the work directly.
- Pure requirements clarification with no execution → use `neurosis` alone.
- Nightly self-improvement → that is `morpheus`.

## Run parameter

`goal` — what to complete. Derive a slug from it; keep state at
`~/.birkin/boulder/<slug>.json` so the run is **resumable** after an interruption.

## Procedure

### Phase 1 — clarify (only if vague)

If the goal lacks a clear target / constraints / acceptance, run the **neurosis**
skill first (`load_skill('neurosis')`) to a spec. If the goal is already specific,
skip straight to planning.

### Phase 2 — plan (Boulder)

Write a **checkbox plan** to `~/.birkin/boulder/<slug>.json`: an ordered list of
small, independently-verifiable steps, each with a one-line **acceptance
criterion**. This is the durable "Boulder" — progress survives restarts; on resume,
read it and continue from the first unchecked step. Mirror each step to the
append-only ledger.

### Phase 3 — adversarial critique (Hyperplan)

Before executing, have **N adversarial critics** (default 3; use read-only
subagents) attack the plan: missing steps, wrong order, untestable criteria, risky
actions. Revise the plan once from their findings. (Cheap insurance against
confidently doing the wrong thing.)

### Phase 4 — execute one step at a time

For each unchecked step, in order:

```
[Odyssey] step {i}/{n} | {step title} | 예상 남은 단계: ~{remaining}
```

1. **Pick the model by task class** (Model Router): trivial/mechanical →
   `haiku`; reasoning/architecture/ambiguous → `opus`; default `sonnet`. Stay
   within the subscription tier (free) — never the paid API.
2. **Edit files with hash-checked writes only** (Hashline): read first (lines are
   tagged `LINE#ID`), and refuse to write if the line hash is stale — re-read and
   retry instead of clobbering.
3. **No consequential side effects without approval**: shell/cron go to the
   approval queue (`approvals.py`); never auto-run them inside the cycle.

### Phase 5 — verify each step (Osiris)

After a step, **Osiris** checks the result against that step's acceptance
criterion (independent pass — fresh eyes, ideally a separate model):

```
[Osiris] step {i}: PASS — {one-line evidence}        → check the box
[Osiris] step {i}: FAIL — {what's missing}           → retry the step (≤ cap)
```

Cap retries per step (default 3) and total iterations (default ~100; ~500 only if
the user explicitly asked for an exhaustive run). On repeated failure, stop and
report what's blocking — do not loop forever.

### Phase 6 — done

Stop when **every box is checked AND Osiris confirms the overall goal**. Summarize:
what was done, what was queued for approval, what (if anything) remains. Persist a
short result to memory if it is durable knowledge.

## Output

- `~/.birkin/boulder/<slug>.json` — the resumable checkbox plan + per-step verdicts.
- Files changed via hash-checked edits; consequential actions queued in
  `~/.birkin/pending/` for `birkin review`.
- A run record (`birkin runs` / `birkin trace <id>`).

## Notes

- **Progress as remaining steps, not internals** (e.g. "예상 남은 단계: ~3") —
  same spirit as neurosis showing remaining questions.
- **Resume-safe**: every step's state is on disk before the next; a crash or
  context-limit resumes from the Boulder file.
- **Graceful today**: until a dedicated runtime ships, run these phases manually
  with current tools — maintain the
  plan file yourself, route models via `/model`, verify inline, spawn critics as
  subagents. See `docs/v2.md` for the build order.
