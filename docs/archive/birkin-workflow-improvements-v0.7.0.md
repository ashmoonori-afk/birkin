# Birkin Workflow System — 5 Improvements Spec

> For Claude Code execution. Each item builds on the previous. Execute in order 1→5.

---

## 1. Workflow Recommender Engine

**Problem**: InsightsEngine detects patterns and ProfileCompiler extracts user profiles, but nothing connects these signals to actionable workflow suggestions.

**New file**: `birkin/core/workflow/recommender.py`

**Design**:
```python
class WorkflowRecommender:
    """Analyzes memory + insights to proactively suggest workflows."""

    def __init__(self, wiki: WikiMemory, insights: InsightsEngine, event_store: EventStore):
        self.wiki = wiki
        self.insights = insights
        self.event_store = event_store

    async def suggest(self, top_k: int = 3) -> list[WorkflowSuggestion]:
        """Generate workflow suggestions based on user behavior patterns.

        Pipeline:
        1. Pull recent patterns from InsightsEngine.identify_patterns()
        2. Pull user profile from WikiMemory (category="entities", look for profile pages)
        3. Pull recent session summaries from WikiMemory (category="sessions")
        4. Detect repetition signals:
           - Same tool called 3+ times in different sessions → "automate this"
           - Same topic discussed 3+ times in 7 days → "create a workflow for this"
           - High-frequency time-of-day usage → "schedule this"
        5. Match against existing sample workflows (birkin_workflows.json)
           - If close match exists → suggest with customization
           - If no match → generate draft via NLWorkflowBuilder
        6. Rank by (frequency × recency × user_profile_relevance)
        7. Return top_k WorkflowSuggestion objects
        """

    async def detect_repetitions(self, days: int = 14) -> list[RepetitionSignal]:
        """Scan EventStore for repeated action patterns.

        Look for:
        - tool_call events with same tool name across 3+ sessions
        - llm_call events with similar prompts (cosine similarity > 0.8 via SemanticSearch)
        - session topics that cluster together
        """

    def _score_suggestion(self, signal: RepetitionSignal, profile: dict) -> float:
        """Score = frequency * recency_decay * profile_match.

        - frequency: how many times the pattern appeared
        - recency_decay: exp(-0.1 * days_since_last)
        - profile_match: 1.0 if matches user expertise/interests, 0.5 otherwise
        """
```

**Data models** (add to `birkin/core/models.py` or same file):
```python
@dataclass
class RepetitionSignal:
    pattern_type: str          # "tool_repeat" | "topic_repeat" | "schedule_repeat"
    description: str           # human-readable: "You summarize HN articles 4x/week"
    frequency: int             # occurrence count
    last_seen: datetime
    related_events: list[str]  # event IDs

@dataclass
class WorkflowSuggestion:
    title: str                 # "Auto-summarize HackerNews daily"
    description: str           # why this is suggested
    confidence: float          # 0.0-1.0
    source_signal: RepetitionSignal
    draft_workflow: dict | None  # pre-built graph JSON if available
    sample_match: str | None     # ID of matching sample workflow
```

**Wire into gateway**: Add `GET /api/workflows/suggestions` endpoint in `birkin/gateway/routers/workflows.py`:
```python
@router.get("/workflows/suggestions")
async def get_suggestions(top_k: int = 3) -> list[dict]:
    recommender = WorkflowRecommender(wiki, insights, event_store)
    suggestions = await recommender.suggest(top_k=top_k)
    return [s.__dict__ for s in suggestions]
```

**Difficulty**: L | **Effort**: 4-6h

---

## 2. Proactive Workflow Discovery (Push Notifications)

**Problem**: Suggestions exist only when user asks. The system should proactively surface recommendations.

**Location**: `birkin/core/workflow/recommender.py` (extend) + `birkin/triggers/scheduler.py` + `birkin/gateway/app.py`

**Changes**:

Add a periodic check that runs after each session ends AND on a daily schedule:

```python
# In WorkflowRecommender, add:
async def check_and_notify(self) -> list[WorkflowSuggestion]:
    """Run after session end or daily. Only surface NEW suggestions.

    1. Generate suggestions via self.suggest()
    2. Compare against previously dismissed suggestions (stored in wiki category="meta")
    3. Filter out dismissed ones
    4. If any new suggestion has confidence > 0.7, emit a notification event
    """
    suggestions = await self.suggest()
    dismissed = self._load_dismissed()
    new = [s for s in suggestions if s.title not in dismissed]
    high_conf = [s for s in new if s.confidence > 0.7]

    for s in high_conf:
        self.event_store.append(Event(
            type="workflow_suggestion",
            payload={"title": s.title, "description": s.description, "confidence": s.confidence}
        ))

    return high_conf
```

**Hook into session lifecycle** in `birkin/core/session.py`:
```python
# At session end (after compile_session if it exists):
async def on_session_end(self):
    # ... existing cleanup ...
    if self.recommender:
        new_suggestions = await self.recommender.check_and_notify()
        if new_suggestions:
            # Surface in next session's system prompt via build_context()
            pass
```

**Hook into cron** in `birkin/gateway/app.py` (use existing daily cron from memory improvements):
```python
# Add to the daily 3AM task:
await recommender.check_and_notify()
```

**Surface in UI**: Add suggestions to the web UI response in `birkin/gateway/routers/chat.py` — include pending suggestions in the chat response metadata so the frontend can render them.

**Difficulty**: M | **Effort**: 3-4h

---

## 3. Memory ↔ Workflow Bridge

**Problem**: Compile memory and workflow engine are parallel systems. Memory should feed workflow context, and workflow results should feed back into memory.

**Location**: `birkin/core/workflow_engine.py` + `birkin/memory/wiki.py`

**Changes**:

### 3a. Memory → Workflow (context injection)
```python
# In WorkflowEngine, modify execute_node() for "llm" type nodes:
async def _execute_llm_node(self, node, inputs, context):
    # NEW: inject relevant memory into LLM prompt
    if self.wiki:
        query = inputs.get("prompt", "") or str(inputs)
        memory_context = self.wiki.build_context(query=query, max_tokens=500)
        # Prepend memory context to the LLM system prompt
        node_config = node.get("config", {})
        system = node_config.get("system_prompt", "")
        node_config["system_prompt"] = f"## Relevant Memory\n{memory_context}\n\n{system}"
```

### 3b. Workflow → Memory (result capture)
```python
# In WorkflowEngine, after workflow completes:
async def _on_workflow_complete(self, workflow_id, results):
    """Write workflow execution summary to memory."""
    if self.wiki:
        summary = self._summarize_results(results)
        self.wiki.ingest(
            category="sessions",
            slug=f"workflow-{workflow_id}-{datetime.now():%Y%m%d}",
            content=summary,
            metadata={"source": "workflow_engine", "confidence": 0.7}
        )
```

### 3c. Recommender reads workflow history from memory
```python
# In WorkflowRecommender.suggest(), add:
# Pull past workflow results from wiki to avoid re-suggesting failed workflows
past_runs = [p for p in self.wiki.list_pages() if p.slug.startswith("workflow-")]
failed_workflows = [p.slug for p in past_runs if "failed" in p.content.lower()]
suggestions = [s for s in suggestions if s.title not in failed_workflows]
```

**Dependency**: Ensure `WorkflowEngine.__init__` accepts an optional `wiki: WikiMemory` parameter. Check current constructor and add if missing.

**Difficulty**: M | **Effort**: 3-4h

---

## 4. Intent-Based Skill Trigger Matching

**Problem**: `SkillRegistry.triggers_match()` uses case-insensitive substring comparison. Can't handle semantic intent ("거래처에 견적서 전달해" → email skill).

**Location**: `birkin/skills/registry.py`

**Changes**:

```python
# Replace or augment the existing triggers_match method:

class SkillRegistry:
    def __init__(self, skills_dir, semantic_search: SemanticSearch | None = None):
        # ... existing init ...
        self._semantic = semantic_search
        self._trigger_embeddings_built = False

    def _build_trigger_index(self):
        """Pre-compute embeddings for all skill triggers + descriptions."""
        if not self._semantic or self._trigger_embeddings_built:
            return
        for skill in self._skills.values():
            # Index skill description + all trigger phrases
            texts = [skill.description] + getattr(skill, 'triggers', [])
            for text in texts:
                self._semantic.index(
                    id=f"skill:{skill.name}:{text}",
                    text=text,
                    metadata={"skill_name": skill.name}
                )
        self._trigger_embeddings_built = True

    def triggers_match(self, text: str) -> list[Skill]:
        """Match user text to skills using hybrid approach.

        1. Exact substring match (existing behavior — fast path)
        2. If no exact match AND semantic_search available:
           - semantic search against trigger index
           - threshold: similarity > 0.6
        3. Return union, deduplicated, sorted by relevance
        """
        # Fast path: existing substring match
        exact = self._exact_match(text)

        if exact or not self._semantic:
            return exact

        # Semantic fallback
        self._build_trigger_index()
        results = self._semantic.search(text, top_k=3)
        semantic_matches = []
        for r in results:
            if r.score > 0.6:
                skill_name = r.metadata.get("skill_name")
                skill = self._skills.get(skill_name)
                if skill and skill not in exact:
                    semantic_matches.append(skill)

        return exact + semantic_matches

    def _exact_match(self, text: str) -> list[Skill]:
        """Original substring matching logic."""
        # Move current triggers_match body here
```

**Bilingual benefit**: SemanticSearch uses SentenceTransformer which handles Korean naturally. "견적서 전달" will match "send email" if the model is multilingual.

**Dependency**: SemanticSearch instance must be injectable into SkillRegistry. Pass via constructor from app.py.

**Difficulty**: M | **Effort**: 2-3h

---

## 5. Suggestion Feedback Loop

**Problem**: When a user accepts, modifies, or dismisses a workflow suggestion, that signal is lost. Next time the same suggestion appears again.

**Location**: `birkin/core/workflow/recommender.py` + new API endpoints

**Changes**:

### 5a. Feedback storage (wiki-based)
```python
# Store feedback as a wiki page in category "meta"
FEEDBACK_SLUG = "workflow-feedback"

class WorkflowRecommender:
    def record_feedback(self, suggestion_title: str, action: str, modification: str = ""):
        """Record user feedback on a suggestion.

        Args:
            suggestion_title: which suggestion
            action: "accepted" | "modified" | "dismissed" | "deleted_after_use"
            modification: what the user changed (if modified)
        """
        page = self.wiki.get_page("meta", FEEDBACK_SLUG)
        existing = yaml.safe_load(page.content) if page else []

        existing.append({
            "title": suggestion_title,
            "action": action,
            "modification": modification,
            "timestamp": datetime.now().isoformat()
        })

        self.wiki.ingest(
            category="meta",
            slug=FEEDBACK_SLUG,
            content=yaml.dump(existing),
            metadata={"source": "recommender", "confidence": 1.0}
        )

    def _load_dismissed(self) -> set[str]:
        """Load previously dismissed suggestion titles."""
        page = self.wiki.get_page("meta", FEEDBACK_SLUG)
        if not page:
            return set()
        records = yaml.safe_load(page.content) or []
        return {r["title"] for r in records if r["action"] == "dismissed"}
```

### 5b. Feedback-weighted scoring
```python
def _score_suggestion(self, signal, profile) -> float:
    base = signal.frequency * math.exp(-0.1 * days_since_last) * profile_match

    # Apply feedback history
    feedback = self._get_feedback_for(signal.description)
    if feedback:
        if feedback["action"] == "dismissed":
            return 0.0  # never suggest again
        elif feedback["action"] == "modified":
            base *= 1.3  # user engaged but wanted changes → good signal
        elif feedback["action"] == "accepted":
            base *= 0.5  # already accepted, lower priority for re-suggestion
        elif feedback["action"] == "deleted_after_use":
            base *= 0.2  # tried and rejected

    return base
```

### 5c. API endpoints
```python
# In birkin/gateway/routers/workflows.py, add:

@router.post("/workflows/suggestions/{suggestion_id}/feedback")
async def suggestion_feedback(suggestion_id: str, body: FeedbackRequest) -> dict:
    """Record user feedback on a workflow suggestion.

    body: { "action": "accepted" | "modified" | "dismissed", "modification": "" }
    """
    recommender = get_recommender()
    recommender.record_feedback(suggestion_id, body.action, body.modification)
    return {"status": "ok"}
```

**Difficulty**: S | **Effort**: 2-3h

---

## Dependency Graph

```
#1 (Recommender) ──→ #2 (Proactive Discovery)
#1 (Recommender) ──→ #3 (Memory Bridge)
#1 (Recommender) ──→ #5 (Feedback Loop)
#4 (Intent Matching) ── independent
#3 (Memory Bridge) ── independent of #2, #4, #5
```

## Execution Order

```
Phase 1: Foundation
  ① Workflow Recommender Engine (core logic)
  ④ Intent-Based Skill Matching (independent, can parallelize with ①)

Phase 2: Integration
  ③ Memory ↔ Workflow Bridge
  ② Proactive Discovery (depends on ①)

Phase 3: Learning
  ⑤ Suggestion Feedback Loop (depends on ①)
```

## Verification

After each item:
1. Run `pytest tests/` — all existing tests must pass
2. Add new tests (minimum 3 cases per item):
   - #1: test repetition detection, test suggestion scoring, test empty history
   - #2: test notification threshold, test dismissed filtering, test session-end hook
   - #3: test memory injection into LLM node, test workflow result capture, test failed workflow filtering
   - #4: test exact match preserved, test semantic fallback, test Korean intent matching
   - #5: test feedback persistence, test dismissed never resurfaces, test score modification
3. Manual QA: run a real multi-session conversation, verify suggestions appear
4. Token count: measure build_context() output before/after #3 to ensure memory injection stays within budget
