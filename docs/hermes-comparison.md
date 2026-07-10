# birkin vs hermes-agent — gap plan, moat plan, daemon architecture

*2026-07-09. References: NousResearch/hermes-agent (modular daemon, 40+ tools,
multi-terminal backends, FTS5 recall), code-yeongyu/senpi (per-model prompt
presets over a dynamic system prompt; no daemon).*

## 1. Comparison

| axis | hermes-agent | birkin | verdict |
|---|---|---|---|
| runtime deps | Node/TS stack | **Python stdlib only** | **moat** |
| memory | MEMORY.md/USER.md + FTS5 session search | **Mnemosyne**: BM25+bigram vault, usage decay, zone priority (benchmarked: LongMemEval R@5 0.968) | **moat** |
| curation safety | agent-curated (model does the writes) | **CurationPlan/1**: typed plan + deterministic executor, safety enforced in code | **moat** |
| provider portability | many providers | claude/codex/api/gemini/ollama via one `complete()` contract | par |
| gateway channels | Telegram, Discord, Slack, WhatsApp, Signal | Telegram + local HTTP | **gap** |
| terminal backends | local, Docker, SSH, Modal, Daytona… | local only | gap (deliberate: personal, one machine) |
| session recall | FTS5 + LLM cross-session recall | sessions tool (full-text) | par-ish |
| daemon/resource mgmt | modular daemon system | scheduler loop + gateway each own resources | **gap → this doc** |
| per-model tuning | model portability, no preset layer | none (one prompt for all engines) | **gap → presets.py** |
| subagents | isolated parallel subagents | depth-bounded subagents | par |
| cost tracking | /usage + budgets | budget caps + runs usage (JSON scan) | gap → ledger |

## 2. Gap improvement plan

1. **Daemon resource layer** — DONE: `ledger.py` (SQLite events + usage),
   `pools.SessionPool` (idle-TTL + LRU cap, gateway wired, 60 s sweep).
2. **Per-model presets** — DONE: senpi-style overlays, strengthened into
   directive guideline blocks per family (§5). `birkin/presets.py`.
3. Channels (Discord/Slack): later; channel interface already pluggable.
4. Remote terminal backends: **YAGNI** for a personal single-machine agent;
   revisit if the user ever runs birkin against remote hosts.

## 3. Moat plan (defend what's ahead)

- **Mnemosyne**: keep zero-dep + benchmarked; standalone repo published
  (`birkin-mnemosyne`) so it's adoptable from hermes/openclaw — the moat is
  the evidence, keep the harness runnable.
- **CurationPlan/1**: safety-by-executor is the differentiator vs
  agent-curated memory (hermes) — keep invariants regression-pinned; extend
  the same plan-only pattern to any future write-path (e.g. skill editing).
- **stdlib-only**: never add a runtime dep; benchmark-only deps stay in
  extras.

## 4. Daemon architecture (requested shape → birkin mapping)

```
Daemon (scheduler loop + gateway process)
├─ Run manager          = store.save_run (exists) → mirrored into ledger
├─ Agent session pool   = pools.SessionPool (NEW) — warm ClaudeStreamSessions
│                          keyed (provider, model, chat), idle-TTL eviction,
│                          max-size cap; gateway adopts it (was: unbounded dict)
├─ Worktree manager     = STUB (birkin edits no repos; ponytail: add when a
│                          coding workflow lands)
├─ MCP connection pool  = config-level: birkin holds no live MCP conns (the
│                          claude CLI does); pooling = reuse of mcp-config +
│                          warm sessions already carrying them
├─ LSP connection pool  = STUB (no LSP consumer anywhere in birkin)
├─ Shell/session pool   = SKIPPED (cron shell jobs are one-shot subprocesses;
│                          a persistent shell saves ~50 ms and adds state bugs)
├─ SQLite event ledger  = ledger.py (NEW, stdlib sqlite3, WAL) — every run,
│                          session open/evict, cron fire; one queryable stream
└─ Cost/budget tracker  = ledger.usage(day|month) + config caps (replaces
                           JSON runs-dir scan for budget accounting)
```

Resource wins: bounded warm-session count (TTL eviction instead of
grow-forever dict), one SQLite file instead of N JSON scans for usage, no
duplicate warm sessions per surface.

## 5. Per-model presets (senpi-inspired)

senpi layers per-model system-prompt presets over a shared dynamic prompt and
swaps tool behavior per family (Claude native tools; GPT codex-style
apply_patch; service tiers). birkin equivalent — `presets.py`:

- **resolve(model) → preset** by family match (opus / sonnet / haiku /
  gpt-5.x / codex-spark / ollama); `cfg["model_presets"]` overrides per field.
- **role overlay**: a *strong directive block* per family — ROLE / APPROACH /
  TOOLS / OUTPUT (and VERIFY for opus) — not a soft hint. All six families
  carry one, including sonnet (the everyday-driver contract). Fast families
  (haiku, spark, local) are marked STRICT: hard tool-call limits, artifact-only
  output, "say so and stop" on out-of-scope tasks.
- **tool profile**: registry filter by group or tool name (haiku/spark/local
  drop web+subagent; gpt drops subagent; opus/sonnet get everything).
- **work style** examples: opus = plan-in-one-line then act, verify before
  claiming done; haiku = answer first, ≤1 tool call, 1-5 sentences; spark =
  requested artifact only, zero prose; gpt/codex = typed plans and full
  replacement blocks, never a description of an edit.

Wired at the two choke points every surface passes through: promptgate
(system prompt, `## Engine preset` section) and build_registry (tools).
Guideline strength is regression-pinned in tests/test_daemon_layer.py.
