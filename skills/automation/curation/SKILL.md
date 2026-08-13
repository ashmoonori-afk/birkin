---
name: memory-curation
description: "Model-agnostic memory-vault curation (CurationPlan/2). Any model proposes a typed reorganization plan; a deterministic executor validates, clamps, and applies only the safe parts. Never deletes; never mass-archives; injection-immune by construction."
version: 1.0.0
author: birkin
license: MIT
metadata:
  birkin:
    tags: [automation, memory, curation, nightly, provider-agnostic]
    entrypoint: "python benchmarks/bench_curation.py --provider <claude|codex|api|gemini|local>"
    module: birkin.curation
---

# Memory curation — one interface, every model

## When to Use

- The memory vault needs reorganizing: inbox notes filed into zones,
  related notes linked, superseded facts marked, genuinely stale notes
  archived.
- The user asks for it in any of these words: "기억 정리", "메모리 정리",
  "벌트 정리해줘", "노트 정리", "curate memory", "clean up the vault",
  "organize my notes", "file the inbox notes".
- `morpheus` is running its nightly duties and reaches the curation step.
- A curation plan needs proposing or reviewing before it is applied.

## When NOT to Use

- Writing or recalling a single memory — use the memory tools directly.
- The user wants to search the vault, not reorganize it — that is
  `semantic-memory`.
- Anything outside the memory vault: this never touches project files.

Birkin's nightly memory curation (a duty of `morpheus`) reorganizes the
markdown memory vault: file inbox notes into topical zone folders, link related
notes, mark superseded facts, and soft-archive the genuinely stale. The problem
this skill solves is that different model backends used to curate through
**different interfaces** — Claude via birkin's MCP tools, Codex via raw shell
file moves — so results were non-comparable and a weak model (Codex) archived
the entire vault because *safety was trusted to the model's prompt-following*.

CurationPlan/2 makes curation **model-agnostic** by applying the same
mechanical/judgment split birkin uses for retrieval:

- **Judgment (the model).** Every provider is reduced to one contract —
  `complete(prompt) -> text` — and must emit exactly one JSON `CurationPlan`.
  The model never touches files, tools, or a shell.
- **Mechanical (birkin).** A deterministic, stdlib executor
  (`birkin/curation.py`) parses the plan, validates and *clamps* it against a
  pre-run snapshot, and applies only the survivors through `Mnemosyne`.

Because every model runs the identical prompt + schema + gate + scorer,
results are comparable by construction, and every model is usable — a weak one
simply proposes fewer accepted ops, never a damaged vault.

## The contract

The model receives a prompt (built by `curation.build_plan_prompt`) and returns
text containing exactly one fenced JSON object:

```json
{"plan_version": 1,
 "ops": [
   {"op": "rezone",    "slug": "pod-autoscaling", "zone": "kubernetes", "reason": "..."},
   {"op": "link",      "a": "pod-autoscaling", "b": "cluster-ingress", "reason": "..."},
   {"op": "supersede", "stale": "server-region", "by": "server-region-update", "reason": "..."},
   {"op": "archive",   "slug": "abandoned-idea", "reason": "..."}],
 "summary": "one short paragraph"}
```

Ops reference notes by their existing **slug** (never an invented path). The
executor performs the mutation; the model only names intent.

## Safety invariants (enforced in code, not by the prompt)

1. **Never delete** — the schema has no delete op; `archive` only *moves* a note
   to `_archive/` via `Mnemosyne.rezone`.
2. **Archive cap** — at most `max(2, ceil(0.20 × active_notes))` archives per
   pass, applied to the mechanically weakest notes; the overflow is dropped.
3. **Protected notes** — `polarity: negative` warnings, filed-and-linked control
   notes, and configured protected types are never archived.
4. **`_archive` is not a topical zone** — a `rezone` targeting it is dropped.
5. **Path containment** — every op must name a known slug; moves never escape
   the vault.
6. **Summary is inert** — the model's free text is never a control signal; an
   injection canary can only manifest as archive ops (absorbed by 2–3), and the
   forbidden phrase is sanitized from the recorded run.
7. **Fail-safe parsing** — unparseable output → an empty plan → a no-op.

A fully compromised model that emits `archive: every note` therefore produces,
at most, a capped number of archives of only non-protected, weakest notes — the
control zone and negative notes survive by construction.

## Adding a model

Add a `complete(prompt) -> text` adapter in `birkin/providers.py` and register
it in `get_completer`. Built in: `claude`, `codex`, `api` (Anthropic/OpenAI),
`gemini`, `local` (ollama). Nothing else — the prompt, schema, gate, and scorer
are shared.

## Audit & reversibility

Each pass returns a `CurationOutcome` recording the proposed op count, the
accepted ops, the dropped ops **with reasons**, the archive cap, and the
effected mutations. Because every mutation is a file move or an idempotent text
append (never a delete), the change set is a human-readable diff over the
Obsidian vault and is reversible from the before/after snapshot.
