# Mnemosyne — zone-indexed semantic memory (design)

> Status: **approved for build** (2026-07-02). Implements the "memory palace"
> upgrade: zones, a mechanical index, usage-driven decay, and zone priority —
> with Morpheus doing the *judgment* work (correlation, placement) nightly.
> Companion ADR: ADR-040 (added to `DECISIONS.md` when this ships).

## 1. Problem

`memory.py` (the Obsidian vault) is transparent and zero-dependency, but:

1. **Every `search()` / `list_notes()` / `render()` reads and parses every
   note file** — the unresolved half of review finding M4 ("매 호출 전체 vault
   재파싱"). Cost grows linearly with the vault forever.
2. The vault is **flat** — no spatial organization. A memory-palace user model
   (place related things together, find them by walking to the right room)
   has no substrate.
3. **Forgetting is binary** (TTL `expires_at` or nothing). No notion of a note
   being *warm* because it is used, or *cold* because it never is.
4. **Nothing records usage.** Retrieval cannot prefer what the user actually
   touches, and nightly maintenance cannot see what is stale.
5. **Morpheus writes notes but never judges the vault** — no link curation, no
   placement, no consolidation. A-MEM's ablation says exactly these two
   mechanisms (link generation + memory evolution) are what separate an agent
   memory from a pile of notes.

## 2. Goals / non-goals

**Goals**

- G1 — Index-backed retrieval: `search`/`list_notes`/`render` never read more
  than `limit` note files. Refresh by `stat()` fingerprints, not re-reads.
- G2 — Zones: physical subdirectories of the vault (`vault/<zone>/note.md`),
  mempalace-style; mechanical placement at write time; Morpheus re-files at
  night. Obsidian stays fully compatible (wikilinks resolve by basename).
- G3 — Decay engine: continuous effective-strength per note
  (Ebbinghaus/Hebbian, adapted from mempalace `dynamics.py`) **wired into
  ranking** — the part mempalace left unwired.
- G4 — Zone priority engine: per-zone EMA of access, decayed daily, boosts
  retrieval and orders the prompt digest.
- G5 — Morpheus judgment loop: mechanical candidates → LLM judges links /
  placement / staleness (A-MEM's two-step link generation + memory evolution).
- G6 — Zero runtime dependencies, backward-compatible public API
  (`render()`, `tools()`, `search()`, `write_note()` signatures preserved).

**Non-goals**

- Embeddings / vector search (documented future upgrade; BM25 is the v1
  relevance engine). No external DB, no daemon.
- Edge-level dynamics (strength on links). Note-level only in v1.
- Auto-*deleting* user files. Forgetting = ranking + `_archive/` zone, plus
  the existing explicit TTL purge. Files are never destroyed by the engine.
- Multi-process index coherence beyond cheap re-stat (single-user tool).

## 3. Evidence base

| Source | What we take | What we fix/skip |
|---|---|---|
| mempalace (`mempalace/mempalace`: `room_detector_local.py`, `searcher.py`, `dynamics.py`) | Rule-based placement (no LLM in the write path); BM25 k1=1.5 b=0.75; Ebbinghaus `strength·exp(−days/stability)` floor 0.05; Hebbian potentiate with ≥1h spacing gate; scoped (zone) search | Its dynamics are **not wired into ranking** — we wire them. We drop chromadb/embeddings/graph layers entirely (stdlib constraint). |
| A-MEM via OUTTA review (arXiv:2502.12110, blog.outta.ai/230) | Two-step linking: mechanical candidate retrieval → **LLM judges** real links; memory evolution (update neighbors); keep top-k small | Embedding similarity for candidates → replaced by BM25 over the note's own terms. |
| hermes-agent (`agent/curator.py`) | Staleness tiers: unused → stale → **archive, never delete**; curation runs in the background, LLM-free transitions + LLM-judged merges | Curator cadence (7d) → folded into the existing nightly Morpheus instead of a new daemon. |

Decay/priority formulas below are otherwise standard (Ebbinghaus retention,
EMA); constants are ours and documented as tunable.

## 4. Approaches considered

- **A. Logical zones only** (frontmatter field, files stay flat) + JSON index.
  Least invasive, but the palace is invisible in Obsidian's file tree, and
  placement judgment has no physical consequence — weaker user model fit.
- **B. Physical zone directories + JSON sidecar index + BM25 + dynamics.**
  **Chosen.** Matches the mempalace mental model the user asked for; Obsidian
  renders zones as folders; index makes it fast; dynamics live in a separate
  state file so the index stays a pure rebuildable cache.
- **C. SQLite FTS5** (stdlib `sqlite3`). BM25 for free, but FTS5 availability
  varies across distro Pythons, the file is opaque (vs a debuggable JSON), and
  CJK still needs custom tokenization anyway. Rejected for v1; revisit if a
  vault exceeds ~10k notes.

## 5. Architecture

```
vault/
├── inbox → (zone-less legacy files at vault root; Morpheus files them away)
├── identity/    people/    projects/    knowledge/    journal/
├── _archive/                  ← excluded from search/render by default
├── .birkin-index.json         ← CACHE (rebuildable): postings, doclen, note meta
└── .birkin-dynamics.json      ← STATE (persistent): per-note dynamics, zone EMA
```

- **`birkin/mnemosyne.py`** (new, ~450 lines): the mechanical engine. No LLM
  calls, no imports from `llm`/`agent`. Tokenizer, inverted index, BM25,
  dynamics (pure functions), zone priority, staleness, related-candidates.
- **`birkin/memory.py`** (modified): `VaultMemory` keeps its API; delegates
  ranking/lookup to a lazy `Mnemosyne`; zone-aware paths; access recording;
  two new tools; zone-aware `render()`.
- **`birkin/morpheus.py`** (modified): task template gains a curation step
  fed with mechanical context (recent notes, stale candidates).
- `mcp_server.py` / `tools.build_registry` need **no changes** — they iterate
  `memory.tools()`.

### 5.1 Zones

- A zone is a directory directly under the vault; name = slug
  (`^[a-z0-9][a-z0-9-]{0,31}$`). Reserved: `_archive`. Root-level files are
  the implicit **inbox** (zone `""`, displayed as `inbox`).
- Seed placement is a pure function of note type (mempalace
  `FOLDER_ROOM_MAP` analog):
  `person→people, project→projects, preference→identity, fact→knowledge,
  topic→knowledge, session→journal`.
- `write_note(..., zone=...)` optional explicit override; otherwise the type
  map decides **for new notes only**. Existing notes always update in place
  (no surprise moves; `updated`-in-place is what optimistic versioning
  expects).
- `rezone(title, zone)` moves the file (creating the zone dir if new, capped
  at 24 zones) and updates the index. Exposed as tool `memory_rezone` — this
  is Morpheus's placement instrument. Moving to `_archive` is the standard
  "forget softly" action (hermes curator: archive, never delete).
- Upgrade migration: **none**. Legacy flat files stay in the inbox until
  Morpheus (or the user) files them. Index builds lazily on first use.

### 5.2 Index (`.birkin-index.json`) — cache, rebuildable

```jsonc
{ "version": 1,
  "notes": { "<slug>": {
      "title": "…", "rel": "knowledge/foo.md", "zone": "knowledge",
      "type": "fact", "tags": ["…"], "links": ["<slug>", …],
      "created": "2026-07-02", "updated": "2026-07-02",
      "confidence": 0.7, "polarity": "positive", "expires_at": null,
      "summary": "first body line ≤120 chars",
      "mtime": 1751400000.0, "size": 812, "doclen": 87 } },
  "postings": { "<term>": { "<slug>": 3 } },     // term → slug → tf
  "avgdl": 92.4 }
```

- **Refresh**: `os.scandir` the vault (root + zone dirs, one level), compare
  `(mtime, size)` per `.md`; only changed/new files are read and re-tokenized;
  deleted files are pruned. A stat pass over a few thousand notes is
  milliseconds — this is G1 (*no re-parsing*, not no statting). Every
  retrieval call runs the stat pass so externally edited notes (Obsidian)
  are visible immediately; add throttling only if a real vault ever exceeds
  ~10k notes (same revisit point as FTS5).
- **Tokenizer** (Korean-aware, stdlib): lowercase; ASCII `[a-z0-9]+` words;
  Hangul runs emitted whole **plus** all character bigrams of each run
  (`"메모리"` → `메모리, 메모, 모리`). Bigrams give substring-ish recall for
  Korean without a morphological analyzer.
- Corruption or version mismatch → full rebuild (it's a cache). Atomic write
  via the existing `_atomic_write`; all mutation under one module `RLock`.

### 5.3 Dynamics (`.birkin-dynamics.json`) — state, survives rebuilds

Per note: `{"strength": s, "stability": σ, "access_count": n,
"last_access": iso}`. Per zone: `{"ema": e, "last_hit": iso-date}`.

Pure functions (each returns a **new** dict — no mutation):

- **Effective strength** (read time, never written):
  `eff(note, now) = max(0.05, s · exp(−Δdays(now, last_access) / σ))`
  — Ebbinghaus retention as in mempalace `dynamics.py` (floor 0.05: nothing
  fully vanishes).
- **Potentiate** (on access):
  `s ← min(5.0, s + 0.25)`;
  if `Δhours ≥ 1`: `σ ← min(365.0, σ · 1.5)`; `n ← n+1`; `last_access ← now`.
  Deviations from mempalace (+0.05 / +0.1 additive) are deliberate: those
  constants were tuned for *edge co-occurrence*, not note access; a personal
  vault sees few accesses, so salience must move in ~20 touches, and spaced
  repetition grows intervals multiplicatively (SM-2 family), so stability
  multiplies. Initial `s=1.0, σ=7.0` (a week — additive 1.0 would floor
  everything in 3 days), `last_access = created`.
- **Zone EMA** (on access to a note in zone z):
  `e ← e · 0.9^Δdays(last_hit) + 1`; `priority(z) = e / max_z(e)` ∈ [0,1].

**What counts as an access:** `get_note` (full read) and `write_note`.
`search`/`render` do **not** potentiate — browsing a result list is not use;
this keeps the loop honest (the agent must actually open a note).

**Staleness** (mechanical feed for Morpheus):
`stale = eff < 0.1 and Δdays(last_access) > 90` — hermes curator's archive
tier. Surfaced as data; the *decision* to archive is Morpheus's (LLM), the
*action* is `memory_rezone(title, "_archive")` (auto-approved: memory
category is reversible).

### 5.4 Search pipeline

1. Tokenize query → **BM25** over postings (Okapi; `k1=1.5, b=0.75`,
   `idf = ln(1 + (N−df+0.5)/(df+0.5))`) → top-32 candidates. Zero file reads.
2. Final score: `bm25 · (1 + 0.3·(eff/5.0) + 0.2·priority(zone))`.
   Relevance dominates; usage and place warm the ranking. `_archive` and
   TTL-expired notes are skipped (unless `zone="_archive"` is requested).
   Tie-break: `updated` desc.
3. Read **only the top-`limit` files** for snippets.
4. Each hit lists its linked slugs from the index (`→ related: [[x]]`) —
   the cheap analog of mempalace's closet/neighbor expansion and A-MEM's
   link-following, at zero extra reads.
5. Optional `zone=` filter (scoped search, mempalace wing/room filter).

### 5.5 `render()` — zone-aware digest

- Line 1 unchanged (vault path, count, tool hint).
- `identity` zone first (≤5 notes), then zones ordered by `priority`,
  each as `## zone (priority)` with its top notes by `eff` (slots split
  proportionally, total default 25). Inbox appears last labeled `inbox` —
  standing nudge that Morpheus has filing to do.
- Per-note line format unchanged (`[[title]] (type): first-line`), polarity
  warning tag preserved.

### 5.6 Morpheus curation step (the judgment half)

Appended to `_MORPHEUS_TASK` as step 1b with mechanical context injected:

- *Recent notes* (created/updated ≤24 h, ≤15) — for each, call
  `memory_related` (mechanical BM25 candidates from the note's own top terms,
  excluding already-linked), **judge** which are truly related →
  `memory_link`; judge whether the note sits in the right zone →
  `memory_rezone`. Update neighbor notes whose content the new note
  supersedes (A-MEM memory evolution).
- *Stale candidates* (≤15, from `stale()`) — judge each: still relevant →
  touch it with a one-line refresh (`write_note` append) or link it into
  place; obsolete → `memory_rezone(title, "_archive")`. Never delete.

New tools on `VaultMemory.tools()` (auto-exposed to registry + MCP):

| Tool | Input | Behavior |
|---|---|---|
| `memory_related` | `title`, `limit=5` | Top BM25 candidates using the note's own terms; excludes self + existing links. LLM-free. |
| `memory_rezone` | `title`, `zone` | Move note file to `vault/<zone>/`, update index. Creates zone if new (≤24 zones). |

`memory_write_note` gains optional `zone` (string) input.

### 5.7 CLI

`birkin reindex` — force full rebuild, print stats (notes, zones, terms,
stale count). Debug/ops hatch; everything else is lazy.

## 6. Concurrency & failure

- One module `RLock` guards index+dynamics load/mutate/flush; note files keep
  the existing per-slug locks; all JSON writes go through `_atomic_write`.
- Index unreadable/stale-version → rebuild silently. Dynamics unreadable →
  fresh defaults (worst case: warmth resets; never crashes memory access).
- A note file referenced by the index but missing on disk → entry pruned on
  next refresh; `get_note` falls back to an `rglob` scan before failing.
- Zone dir creation races: `mkdir(parents=True, exist_ok=True)`.
- `rezone` of a note that vanished → tool returns `is_error`, no partial
  index update.

## 7. Testing plan (TDD; offline; isolated `BIRKIN_HOME`)

- **Pure functions, exact values**: tokenizer (ASCII/Hangul/bigram), BM25
  (hand-computed 2-doc case), `eff` decay curve (0 d → s; σ days → s·e⁻¹;
  floor), potentiate (spacing gate: <1 h no σ growth; caps), zone EMA decay.
- **Index**: build → incremental (touch one file → only it re-read; verified
  via read counter monkeypatch) → delete pruned → corrupted JSON rebuild →
  version bump rebuild.
- **Zones**: type→zone placement of new notes; legacy root note updates stay
  in place; rezone moves file + index + wikilinks still resolve; `_archive`
  excluded from search/render; zone cap enforced.
- **Search**: ranking (relevant beats warm-but-irrelevant; warm beats cold at
  equal BM25; zone priority boost measurable), snippet only reads top files,
  zone filter, related-links line, Korean query round-trip.
- **Dynamics wiring**: `get_note`/`write_note` potentiate; `search`/`render`
  do not; stale() tiers.
- **render**: identity first, priority order, inbox label, polarity tag.
- **Tools**: `memory_related`, `memory_rezone`, `memory_write_note(zone=…)`
  happy + error paths. **Morpheus**: task text contains recent/stale blocks.
- **Compat**: whole existing `test_memory.py` / `test_memory_os.py` suites
  pass unmodified. Coverage stays ≥75 %.

## 8. Constants (single source in `mnemosyne.py`)

`K1=1.5 B=0.75 CAND=32 STRENGTH_STEP=0.25 STRENGTH_CAP=5.0 STABILITY_INIT=7.0
STABILITY_GROWTH=1.5 STABILITY_CAP=365.0 EFF_FLOOR=0.05 SPACING_HOURS=1.0
ZONE_EMA_DECAY=0.9 W_DYN=0.3 W_ZONE=0.2 STALE_EFF=0.1 STALE_DAYS=90
MAX_ZONES=24 RELATED_LIMIT=5`

All tunable in one place; none are config keys in v1 (YAGNI — promote to
config only when a real need appears).
