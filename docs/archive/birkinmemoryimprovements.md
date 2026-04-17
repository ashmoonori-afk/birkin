# Birkin Memory System — Validated Improvement Spec

> For Claude Code execution. Each item is independently implementable. Execute in P0 → P1 → P2 order.

---

## P0: Ship Now (North Star Critical)

### 1. build_context() Relevance Scoring

**Problem**: `build_context()` dumps all wiki pages into the system prompt. Token count explodes as pages grow — directly conflicts with the "token savings" roadmap goal.

**Location**: `birkin/memory/wiki.py` → `build_context()` method

**Changes**:
```
Current: concatenates ALL wiki pages into a single string and returns it
Target:
1. Use SemanticSearch.search(current_query, top_k=5) to filter relevant pages
2. Include [[wikilink]] 1-hop neighbors of matched pages
3. For remaining pages, include only "title + tags" as a compact index (lazy reference)
```

**Signature change**:
```python
def build_context(self, query: str = "", max_tokens: int = 2000) -> str:
```

**Dependency**: Needs a `SemanticSearch` instance accessible from `wiki.py`. Check if it's already reachable — if not, inject via constructor.

**Difficulty**: S | **Effort**: 1-2h | **Side effects**: None (existing callers with `query=""` fall back to full dump for backward compat)

---

### 2. Wire compile_daily() to Cron Trigger

**Problem**: `compile_daily()` is manual-only. Phase 2 roadmap explicitly targets "triggers/cron" — this is the lowest-hanging fruit.

**Location**: `birkin/gateway/app.py` (FastAPI lifespan or startup event)

**Changes**:
```python
# Option A: apscheduler
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()
scheduler.add_job(memory_compiler.compile_daily, 'cron', hour=3)  # daily at 3 AM
scheduler.start()

# Option B (no new dependency): asyncio loop
async def _daily_compile_loop(compiler):
    while True:
        await asyncio.sleep(seconds_until_3am())
        await compiler.compile_daily()
```

**Prefer Option B** to avoid adding apscheduler as a dependency.

**Difficulty**: S | **Effort**: 30min | **Side effects**: None

---

### 3. Memory Poisoning Protection (Prompt Injection Defense)

**Problem**: LLM auto-writes to wiki. Prompt injection can plant false info → `build_context()` propagates it to ALL future sessions.

**Location**: `birkin/memory/wiki.py` → `ingest()` method

**Changes**:
```
1. Sanitize content on ingest():
   - Detect system prompt patterns ("[SYSTEM]", "You are now", "Ignore previous", etc.)
   - Escape instruction-like content inside markdown code blocks
2. Add `source` metadata to each page:
   - "user_confirmed" | "auto_classified" | "compiler_generated"
3. Apply source-based weighting in build_context():
   - user_confirmed: weight 1.0
   - compiler_generated: weight 0.7
   - auto_classified: weight 0.5
```

**Difficulty**: M | **Effort**: 2-3h | **Side effects**: Legitimate technical docs could trigger false positives → needs allowlist for code-heavy content

---

## P1: Incremental Quality

### 4. TTL-Based Session Cleanup

**Problem**: `sessions/` category accumulates session summaries indefinitely.

**Location**: `birkin/memory/wiki.py`

**Changes**:
```python
def cleanup_sessions(self, max_age_days: int = 30):
    """Delete or compress session pages older than TTL."""
    for page in self.list_pages():
        if page.category == "sessions" and page.age_days > max_age_days:
            # Option A: delete
            self.delete_page(page.category, page.slug)
            # Option B: compress (keep title + tags, truncate body)
```

**Wire this into the cron job from #2 — call `cleanup_sessions()` right after `compile_daily()`.**

**Difficulty**: S | **Effort**: 1h

---

### 5. Confidence Score + Source Metadata

**Problem**: LLM-generated pages and user-verified pages carry equal weight.

**Location**: Wiki page metadata (markdown YAML frontmatter)

**Changes — extend page schema**:
```markdown
---
title: "Project X"
category: entities
confidence: 0.6              # NEW — float 0.0-1.0
source: auto_classified       # NEW — auto_classified | compiler_generated | user_confirmed
last_referenced: 2026-04-17   # NEW — for decay calculation
reference_count: 3             # NEW — for decay calculation
---
```

**Behavior**:
- `build_context()` sorts by confidence (descending) before selecting pages
- When user edits a page via API → set `confidence: 1.0`, `source: user_confirmed`
- New auto-classified pages start at `confidence: 0.5`
- Compiler-generated pages start at `confidence: 0.7`

**Difficulty**: M | **Effort**: 2-3h

---

### 6. Wikilink Alias System

**Problem**: "OpenAI" and "오픈AI" become separate nodes. Synonyms, abbreviations, and multilingual variants are not linked.

**Location**: `birkin/memory/wiki.py` → `auto_link()` + page metadata

**Changes**:
```markdown
---
title: "OpenAI"
aliases: ["오픈AI", "GPT company", "openai"]
---
```

```python
def auto_link(self, content: str) -> str:
    for page in self.list_pages():
        targets = [page.title] + getattr(page, 'aliases', [])
        for target in sorted(targets, key=len, reverse=True):  # longest match first
            content = content.replace(target, f"[[{page.slug}|{target}]]")
    return content
```

**Note**: Sort by length descending to prevent partial matches ("AI" matching before "OpenAI").

**Difficulty**: S | **Effort**: 1-2h | **Side effects**: Alias collisions need priority rules (first-registered wins, or explicit override)

---

## P2: Medium-Term Intelligence

### 7. Korean NER Pipeline

**Problem**: `extract_entities()` uses capitalization heuristics. Korean has no capitalization — entity extraction fails entirely for Korean conversations despite the project claiming bilingual support.

**Location**: `birkin/memory/compiler.py` → `extract_entities()`

**Changes**:
```python
# pip install kiwipiepy
from kiwipiepy import Kiwi

kiwi = Kiwi()

def extract_entities(self, text: str) -> list[str]:
    # Keep existing English capitalization heuristic
    entities = self._extract_english_entities(text)
    
    # Add Korean proper noun (NNP) extraction
    for token in kiwi.tokenize(text):
        if token.tag == 'NNP':  # proper noun
            entities.append(token.form)
    
    return list(set(entities))
```

**Dependency**: Add `kiwipiepy` as optional in `pyproject.toml`:
```toml
[project.optional-dependencies]
korean = ["kiwipiepy>=0.17"]
```

Graceful fallback: if kiwipiepy not installed, skip Korean NER and log a warning.

**Difficulty**: M | **Effort**: 2-3h | **Side effects**: First run downloads ~50MB model. Fine for self-hosted; add to docs.

---

### 8. Memory Decay

**Problem**: All pages persist with equal weight forever. No natural forgetting — unlike human memory.

**Location**: `birkin/memory/wiki.py` → `build_context()` + page metadata

**Changes**:
```python
import math

def _decay_score(self, page) -> float:
    """Frequency + time-based decay score."""
    days_since_ref = (datetime.now() - page.last_referenced).days
    base = page.confidence * page.reference_count
    decay = math.exp(-0.05 * days_since_ref)  # ~20-day half-life
    return base * decay
```

**Behavior**:
- `build_context()` ranks pages by `_decay_score()` instead of insertion order
- Periodically (via cron from #2), pages with score below threshold → move to `sessions/` archive or delete
- Every time a page is included in `build_context()` output → bump `reference_count` and `last_referenced`

**Prerequisite**: #5 (confidence score) must be implemented first.

**Difficulty**: M | **Effort**: 2-3h

---

### 9. Hierarchical Summary (Lazy Loading)

**Problem**: Even with relevance scoring, injecting full page content can still consume too many tokens.

**Location**: `birkin/memory/wiki.py` + `birkin/tools/builtins/` (new tool)

**Changes**:
```
1. build_context() injects ONLY "title + tags + 1-line summary" index
2. New tool: wiki_read(category, slug) → returns full page content
3. Agent calls wiki_read on-demand when it needs details
```

```python
# birkin/tools/builtins/wiki_tools.py
class WikiReadTool:
    name = "wiki_read"
    description = "Read the full content of a wiki page. Use slugs from the memory index in the system prompt."
    
    async def run(self, category: str, slug: str) -> str:
        page = self.wiki.get_page(category, slug)
        if page:
            # Bump reference tracking
            self.wiki.touch_page(category, slug)
            return page.content
        return f"Page not found: {category}/{slug}"
```

**Prerequisite**: #1 (relevance scoring) should be implemented first.

**Difficulty**: M | **Effort**: 3-4h

---

## SKIP (Not Needed at Current Scale)

### ~~10. GraphContext Copy-on-Write~~ → DEFERRED
Python lacks native COW. Would need Pyrsistent library — overkill for current scale.
**If needed later**: Use `copy.deepcopy()` snapshot per parallel branch.

### ~~11. Conflict Detection~~ → DEFERRED
Single-user self-hosted environment makes concurrent edits unlikely.
**If needed later**: Hash-compare on `ingest()` → log diff to `log.md`.

### ~~12. MemoryPipeline Unification~~ → DEFERRED
Merging classifier + compiler is a major refactor. Current pipeline works. Revisit after P0/P1.

---

## Execution Order

```
Phase 1 (P0): Token Savings + Safety
  ① build_context() relevance scoring
  ② compile_daily() cron wiring
  ③ Memory poisoning protection

Phase 2 (P1): Quality
  ④ TTL session cleanup
  ⑤ Confidence score + source metadata
  ⑥ Wikilink aliases

Phase 3 (P2): Intelligence
  ⑦ Korean NER (kiwipiepy)
  ⑧ Memory decay
  ⑨ Lazy loading (wiki_read tool)
```

## Dependency Graph

```
#1 (relevance) ──→ #9 (lazy loading)
#2 (cron) ──→ #4 (TTL cleanup)
#3 (poisoning) ──→ #5 (confidence) ──→ #8 (decay)
#6 (aliases) ── independent
#7 (Korean NER) ── independent
```

## Verification

After each item:
1. Run `pytest tests/memory/` — all existing tests must pass
2. Add new tests (minimum 3 cases per item)
3. Measure `build_context()` output token count before/after
4. Manual QA: run a real conversation session and verify memory injection quality
