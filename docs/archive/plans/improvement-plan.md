# Birkin Improvement Plan — Module Wiring Sprint

> **Goal:** Raise the overall North Star score from **53.5 → 70+** by connecting orphaned modules to the live execution path.
>
> **Constraint for Claude Code:** One task at a time. Commit after each task. Run `pytest tests/ -x --tb=short` and `ruff check .` before committing. Do NOT run tasks in parallel.

---

## Current Score Snapshot (v0.3.0)

| North Star            | Score | Grade |
|-----------------------|-------|-------|
| Token Efficiency      | 62    | C+    |
| Work Automation       | 45    | D+    |
| Personalized Evolution| 55    | C     |
| LLM Orchestration     | 52    | C     |
| **Overall**           | **53.5** | **C** |

---

## Task Index

| ID   | Priority | Task                                          | Est. Hours | Score Impact |
|------|----------|-----------------------------------------------|------------|--------------|
| IMP-1 | P0      | Wire MCP + Skills tools into Agent via gateway | 2–3h       | +8           |
| IMP-2 | P0      | Wire ProviderRouter into gateway chat          | 1–2h       | +7           |
| IMP-3 | P0      | Wire Trigger → Workflow execution              | 2–3h       | +12          |
| IMP-4 | P0      | Wire TokenBudget into Agent run loop           | 1–2h       | +5           |
| IMP-5 | P1      | Fix SemanticSearch caching (remove index_all)  | 1h         | +5           |
| IMP-6 | P1      | Wire StructuredLogger into Agent + Provider    | 2h         | +5           |
| IMP-7 | P1      | Integrate StateGraph with WorkflowEngine       | 3–4h       | +8           |
| IMP-8 | P2      | Add sentence-transformers optional dependency  | 1h         | +3           |
| IMP-9 | P2      | Add Voice module tests                         | 1h         | +2           |
| IMP-10| P2      | Trigger persistence (SQLite)                   | 2h         | +3           |

**Total estimated: ~18 hours → projected score 70+ (B-)**

---

## IMP-1: Wire MCP + Skills tools into Agent via gateway

### Why
MCPRegistry and SkillRegistry are fully implemented but orphaned. Agent already accepts `mcp_registry` as an optional kwarg and merges MCP tools at init (agent.py lines 47–57). Gateway never instantiates or passes either registry, so MCP/Skill tools are invisible to the chat endpoint.

### What to change

**File: `birkin/gateway/deps.py`**

Add two new lazy singletons, following the existing pattern used for `get_session_store()` and `get_wiki_memory()`:

```python
from birkin.mcp.registry import MCPRegistry
from birkin.skills.registry import SkillRegistry

_mcp_registry: MCPRegistry | None = None
_skill_registry: SkillRegistry | None = None

def get_mcp_registry() -> MCPRegistry:
    global _mcp_registry
    if _mcp_registry is None:
        from birkin.gateway.config import load_config
        config = load_config()
        _mcp_registry = MCPRegistry()
        for server_cfg in config.get("mcp_servers", []):
            _mcp_registry.add_server(server_cfg)
    return _mcp_registry

def get_skill_registry() -> SkillRegistry:
    global _skill_registry
    if _skill_registry is None:
        from pathlib import Path
        _skill_registry = SkillRegistry(skills_dir=Path("skills"))
        _skill_registry.load_all()
    return _skill_registry

def reset_mcp_registry() -> None:
    global _mcp_registry
    _mcp_registry = None

def reset_skill_registry() -> None:
    global _skill_registry
    _skill_registry = None
```

**File: `birkin/gateway/routers/chat.py`**

In `_build_agent()` (around line 24), add MCPRegistry and skill tools:

```python
from birkin.gateway.deps import get_mcp_registry, get_skill_registry

# Inside _build_agent(), before `return Agent(**agent_kwargs)`:
skill_reg = get_skill_registry()
skill_tools = skill_reg.get_enabled_tools()  # returns list[Tool]
all_tools = load_tools() + skill_tools

agent_kwargs = {
    "provider": provider,
    "tools": all_tools,
    "session_store": store,
    "session_id": body.session_id,
    "memory": get_wiki_memory(),
    "mcp_registry": get_mcp_registry(),
}
```

**File: `birkin/gateway/routers/skills.py`**

Replace the module-level `_get_registry()` with the shared singleton from deps.py:

```python
from birkin.gateway.deps import get_skill_registry
# Remove the local _registry and _get_registry()
# Replace all _get_registry() calls with get_skill_registry()
```

**File: `birkin/gateway/app.py`**

Add cleanup in lifespan shutdown:

```python
from birkin.gateway.deps import reset_mcp_registry, reset_skill_registry

# In lifespan(), after existing resets:
reset_mcp_registry()
reset_skill_registry()
```

### Verification
```bash
pytest tests/mcp/ tests/skills/ tests/gateway/test_routes.py -x --tb=short
ruff check birkin/gateway/deps.py birkin/gateway/routers/chat.py
```

### Acceptance Criteria
- `GET /api/chat` returns tool calls from MCP servers listed in config
- `GET /api/skills` and Agent share the same SkillRegistry instance
- Skills toggled ON via API appear in Agent's tool list on next chat

---

## IMP-2: Wire ProviderRouter into gateway chat

### Why
9 providers exist with ProviderProfile capability metadata, and ProviderRouter.select() is implemented (providers/registry.py lines 95–139). But gateway always creates a single provider from the request body. Auto-routing and fallback chains don't work.

### What to change

**File: `birkin/gateway/deps.py`**

Add a ProviderRegistry + ProviderRouter singleton:

```python
from birkin.core.providers.registry import ProviderRegistry, ProviderRouter

_provider_router: ProviderRouter | None = None

def get_provider_router() -> ProviderRouter:
    global _provider_router
    if _provider_router is None:
        from birkin.core.providers import create_provider
        from birkin.gateway.config import load_config
        config = load_config()
        registry = ProviderRegistry()
        # Register all configured providers
        for name in ["anthropic", "openai", "gemini", "groq", "perplexity", "ollama"]:
            try:
                p = create_provider(f"{name}/default")
                registry.register(p)
            except (ValueError, TypeError, KeyError):
                pass  # provider not configured (no API key)
        _provider_router = ProviderRouter(registry)
    return _provider_router
```

**File: `birkin/gateway/routers/chat.py`**

In `_build_agent()`, if the request does not specify a provider, use the router:

```python
from birkin.gateway.deps import get_provider_router

# Replace the provider creation block:
if body.provider and body.provider != "auto":
    model_str = f"{body.provider}/{body.model}" if body.model else f"{body.provider}/default"
    provider = create_provider(model_str)
else:
    router = get_provider_router()
    provider = router.select(prefer="cost")
    if provider is None:
        raise HTTPException(status_code=400, detail="No provider available")
```

### Verification
```bash
pytest tests/providers/test_capabilities.py tests/gateway/test_routes.py -x --tb=short
```

### Acceptance Criteria
- `POST /api/chat {"provider": "auto"}` selects cheapest available provider
- Explicit provider requests still work as before
- `select_with_fallback()` catches provider errors and retries next

---

## IMP-3: Wire Trigger → Workflow execution

### Why
TriggerScheduler exists, cron/file/webhook/message triggers all fire correctly, but the `_default_on_fire` callback (triggers.py line 33) is a noop `pass`. No trigger actually runs a workflow.

### What to change

**File: `birkin/gateway/routers/triggers.py`**

Replace the noop callback with actual workflow execution:

```python
async def _default_on_fire(config: TriggerConfig) -> None:
    """Execute the linked workflow when a trigger fires."""
    workflow_id = config.metadata.get("workflow_id")
    if not workflow_id:
        logger.warning("Trigger %s fired but has no workflow_id in metadata", config.name)
        return

    from birkin.gateway.workflows import load_workflow
    from birkin.core.workflow_engine import WorkflowEngine
    from birkin.gateway.deps import get_wiki_memory
    from birkin.core.providers import create_provider
    from birkin.gateway.config import load_config

    cfg = load_config()
    provider_name = config.metadata.get("provider", cfg.get("provider", "anthropic"))

    try:
        workflow = load_workflow(workflow_id)
        provider = create_provider(f"{provider_name}/default")
        engine = WorkflowEngine(provider=provider, memory=get_wiki_memory())
        result = await engine.execute(workflow, trigger_context={
            "trigger_name": config.name,
            "trigger_type": config.trigger_type,
            "fired_at": datetime.utcnow().isoformat(),
        })
        logger.info("Trigger %s → workflow %s completed: %s", config.name, workflow_id, result.get("status"))
    except Exception as exc:
        logger.error("Trigger %s → workflow %s failed: %s", config.name, workflow_id, exc)
```

**File: `birkin/gateway/app.py`**

Initialize TriggerScheduler at startup, restore persisted triggers:

```python
# In lifespan(), startup section:
from birkin.gateway.routers.triggers import get_scheduler
scheduler = get_scheduler()
await scheduler.start()

# In lifespan(), shutdown section:
await scheduler.stop()
```

### Verification
```bash
pytest tests/triggers/test_triggers.py -x --tb=short
```

### Acceptance Criteria
- Creating a trigger with `{"metadata": {"workflow_id": "my-flow"}}` actually runs the workflow on fire
- Triggers start on app boot and stop on shutdown
- Errors in workflow execution are logged, not swallowed

---

## IMP-4: Wire TokenBudget into Agent run loop

### Why
TokenBudget (budget/manager.py) and BudgetPolicy (budget/policy.py) are complete implementations. Neither is used in Agent._run_loop() or _run_loop_async(). Token spend is uncontrolled.

### What to change

**File: `birkin/core/agent.py`**

Add TokenBudget as an optional dependency:

```python
from birkin.core.budget.manager import TokenBudget
from birkin.core.budget.policy import BudgetPolicy

class Agent:
    def __init__(
        self,
        ...
        budget: Optional[TokenBudget] = None,
    ) -> None:
        ...
        self._budget = budget
```

In `_run_loop_async()` (the main execution loop), add budget checks:

```python
# Before calling provider.complete() or provider.acomplete():
if self._budget:
    allowed = self._budget.check_before_call(
        estimated_tokens=len(str(messages)) // 4  # rough estimate
    )
    if not allowed:
        yield Message(role="assistant", content="[Budget exceeded — stopping.]")
        return

# After receiving response, record usage:
if self._budget and response.usage:
    self._budget.record_usage(
        tokens_in=response.usage.input_tokens,
        tokens_out=response.usage.output_tokens,
        cost_usd=response.usage.cost_usd or 0.0,
    )
```

**File: `birkin/gateway/routers/chat.py`**

Pass a default budget to Agent:

```python
from birkin.core.budget.manager import TokenBudget
from birkin.core.budget.policy import BudgetPolicy

# In _build_agent():
budget = TokenBudget(policy=BudgetPolicy())  # uses defaults
agent_kwargs["budget"] = budget
```

### Verification
```bash
pytest tests/budget/test_budget.py tests/core/test_agent.py -x --tb=short
```

### Acceptance Criteria
- Agent stops generating when session token budget is exceeded
- Token usage is recorded after each provider call
- Default budget is generous enough to not break existing tests

---

## IMP-5: Fix SemanticSearch caching (remove per-turn index_all)

### Why
In agent.py line 466, `search.index_all()` is called every single turn, re-indexing all wiki pages. With 23+ pages this is wasteful; with 100+ it becomes a bottleneck.

### What to change

**File: `birkin/memory/semantic_search.py`**

Add a dirty flag so index_all() only runs when pages change:

```python
class SemanticSearch:
    def __init__(self, ...):
        ...
        self._indexed_page_count: int = 0

    def index_all(self) -> int:
        """Re-index only if the page count has changed."""
        current_count = len(self._memory.list_pages())
        if current_count == self._indexed_page_count and self._indexed_page_count > 0:
            return self._indexed_page_count  # skip re-index
        # ... existing indexing logic ...
        self._indexed_page_count = current_count
        return current_count
```

**File: `birkin/memory/wiki.py`**

Invalidate the cache on ingest/delete:

```python
# In ingest() and delete_page(), after the write:
if hasattr(self, '_search_cache_dirty'):
    self._search_cache_dirty = True
```

### Verification
```bash
pytest tests/memory/ -x --tb=short
```

### Acceptance Criteria
- Second consecutive `index_all()` call with no page changes returns immediately
- Ingesting a new page triggers re-indexing on next search
- No regression in memory tests

---

## IMP-6: Wire StructuredLogger into Agent + Provider

### Why
StructuredLogger (observability/logger.py) is complete but never called. Zero traces are emitted during actual Agent execution. The observability dashboard has no data to show.

### What to change

**File: `birkin/core/agent.py`**

Add tracing around the main loop:

```python
from birkin.observability.logger import StructuredLogger

# In _run_loop_async(), at the start:
trace = StructuredLogger.start_trace(session_id=self._session.session_id)

# Before each provider call:
span = StructuredLogger.start_span(trace, name="llm_call", metadata={
    "provider": self._provider.__class__.__name__,
    "model": getattr(self._provider, '_model', 'unknown'),
})

# After provider response:
StructuredLogger.end_span(span, metadata={
    "tokens_in": response.usage.input_tokens if response.usage else 0,
    "tokens_out": response.usage.output_tokens if response.usage else 0,
})

# Around each tool execution:
tool_span = StructuredLogger.start_span(trace, name=f"tool:{tool_name}")
# ... execute tool ...
StructuredLogger.end_span(tool_span, metadata={"success": result.success})

# At the end of the loop:
StructuredLogger.end_trace(trace)
```

**File: `birkin/observability/storage.py`**

Ensure TraceStorage flushes to the `traces/` directory automatically.

### Verification
```bash
pytest tests/observability/test_observability.py tests/core/test_agent.py -x --tb=short
```

### Acceptance Criteria
- Every chat turn produces a Trace with at least one Span
- Traces appear in `traces/` directory as JSONL
- `/api/observability/traces` returns real data

---

## IMP-7: Integrate StateGraph with WorkflowEngine

### Why
Two separate workflow engines exist: the original `WorkflowEngine` (BFS, used in production) and the newer `StateGraph/CompiledGraph` (graph/engine.py, orphaned). This creates confusion and dead code. The graph engine supports conditionals, parallel fan-out, and loops that WorkflowEngine lacks.

### What to change

**File: `birkin/core/workflow_engine.py`**

Add a `mode` parameter to select between simple (current BFS) and graph (new StateGraph) execution:

```python
from birkin.core.graph.engine import StateGraph, CompiledGraph

class WorkflowEngine:
    async def execute(self, workflow: dict, **kwargs) -> dict:
        mode = workflow.get("mode", "simple")
        if mode == "graph" and "graph" in workflow:
            return await self._execute_graph(workflow["graph"], **kwargs)
        return await self._execute_simple(workflow, **kwargs)

    async def _execute_graph(self, graph_def: dict, **kwargs) -> dict:
        """Execute using the StateGraph engine."""
        graph = StateGraph.from_dict(graph_def)
        compiled = graph.compile()
        initial_state = {"input": kwargs.get("trigger_context", {})}
        return await compiled.ainvoke(initial_state)

    async def _execute_simple(self, workflow: dict, **kwargs) -> dict:
        """Existing BFS execution (unchanged)."""
        # ... current execute() logic moved here ...
```

### Verification
```bash
pytest tests/graph/test_graph.py tests/gateway/test_workflows.py -x --tb=short
```

### Acceptance Criteria
- Existing simple-mode workflows still work (backward compatible)
- Workflow with `{"mode": "graph", "graph": {...}}` uses StateGraph engine
- Sample workflow migrated as proof

---

## IMP-8: Add sentence-transformers optional dependency

### Why
SemanticSearch falls back to SimpleHashEncoder (SHA-256 pseudo-random vectors). This produces random, non-semantic search results. Real embeddings are the prerequisite for the memory moat.

### What to change

**File: `pyproject.toml`**

Add an optional dependency group:

```toml
[project.optional-dependencies]
dev = [...]
korean = ["kiwipiepy>=0.17,<1"]
embeddings = ["sentence-transformers>=2.2,<3"]
all = ["birkin-agent[korean,embeddings]"]
```

**File: `birkin/core/agent.py`**

In the SemanticSearch initialization, prefer SentenceTransformerEncoder when available:

```python
try:
    from birkin.memory.embeddings.encoder import SentenceTransformerEncoder
    encoder = SentenceTransformerEncoder()
except ImportError:
    from birkin.memory.semantic_search import SimpleHashEncoder
    encoder = SimpleHashEncoder()
```

### Verification
```bash
pip install -e ".[embeddings]" && pytest tests/memory/ -x --tb=short
```

### Acceptance Criteria
- `pip install birkin-agent` still works without sentence-transformers
- `pip install birkin-agent[embeddings]` installs sentence-transformers
- With embeddings installed, SemanticSearch uses real vectors

---

## IMP-9: Add Voice module tests

### Why
birkin/voice/ has 0 tests. STT and TTS implementations will crash without API keys and there's no graceful fallback.

### What to change

**File: `tests/voice/test_voice.py`** (new)

```python
import pytest
from unittest.mock import AsyncMock, patch
from birkin.voice.stt import SpeechToText, OpenAISpeechToText
from birkin.voice.tts import TextToSpeech, OpenAITextToSpeech

class TestSTT:
    def test_abc_interface(self):
        assert hasattr(SpeechToText, 'transcribe')

    @pytest.mark.asyncio
    async def test_openai_stt_no_key_raises(self):
        with patch.dict('os.environ', {}, clear=True):
            stt = OpenAISpeechToText()
            with pytest.raises((ConnectionError, ValueError, RuntimeError)):
                await stt.transcribe(b"fake audio data")

    @pytest.mark.asyncio
    async def test_openai_stt_with_mock(self):
        stt = OpenAISpeechToText()
        with patch.object(stt, '_client') as mock_client:
            mock_client.audio.transcriptions.create = AsyncMock(
                return_value=type('R', (), {'text': 'hello world'})()
            )
            result = await stt.transcribe(b"fake audio")
            assert result == 'hello world'

class TestTTS:
    def test_abc_interface(self):
        assert hasattr(TextToSpeech, 'synthesize')

    @pytest.mark.asyncio
    async def test_openai_tts_with_mock(self):
        tts = OpenAITextToSpeech()
        with patch.object(tts, '_client') as mock_client:
            mock_client.audio.speech.create = AsyncMock(
                return_value=type('R', (), {'content': b'audio bytes'})()
            )
            result = await tts.synthesize("hello")
            assert isinstance(result, bytes)
```

### Verification
```bash
pytest tests/voice/ -x --tb=short
```

### Acceptance Criteria
- At least 6 tests covering STT and TTS
- Tests pass without API keys (fully mocked)
- Graceful error when no API key is set

---

## IMP-10: Trigger persistence (SQLite)

### Why
TriggerScheduler stores triggers only in memory. App restart loses all active triggers and schedules.

### What to change

**File: `birkin/triggers/storage.py`** (new)

```python
import json
import sqlite3
from pathlib import Path
from birkin.triggers.base import TriggerConfig

class TriggerStore:
    def __init__(self, db_path: Path = Path("birkin_sessions.db")):
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS triggers (
                name TEXT PRIMARY KEY,
                config_json TEXT NOT NULL,
                active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._conn.commit()

    def save(self, config: TriggerConfig) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO triggers (name, config_json, active) VALUES (?, ?, 1)",
            (config.name, config.model_dump_json()),
        )
        self._conn.commit()

    def remove(self, name: str) -> None:
        self._conn.execute("DELETE FROM triggers WHERE name = ?", (name,))
        self._conn.commit()

    def load_all_active(self) -> list[TriggerConfig]:
        rows = self._conn.execute(
            "SELECT config_json FROM triggers WHERE active = 1"
        ).fetchall()
        return [TriggerConfig.model_validate_json(row[0]) for row in rows]

    def close(self) -> None:
        self._conn.close()
```

**File: `birkin/triggers/scheduler.py`**

Add persistence on add/remove, restore on start:

```python
from birkin.triggers.storage import TriggerStore

class TriggerScheduler:
    def __init__(self, ..., store: TriggerStore | None = None):
        self._store = store or TriggerStore()

    async def start(self):
        # Restore persisted triggers
        for config in self._store.load_all_active():
            await self.add(config)
        # ... existing start logic ...

    async def add(self, config: TriggerConfig) -> None:
        # ... existing add logic ...
        self._store.save(config)

    async def remove(self, name: str) -> None:
        # ... existing remove logic ...
        self._store.remove(name)
```

### Verification
```bash
pytest tests/triggers/test_triggers.py -x --tb=short
```

### Acceptance Criteria
- Triggers persist in SQLite `triggers` table
- App restart restores previously active triggers
- Removing a trigger deletes from both memory and DB

---

## Execution Order

```
IMP-1 (MCP + Skills wiring)     ← unblocks tool visibility
  ↓
IMP-2 (ProviderRouter wiring)   ← unblocks auto-routing
  ↓
IMP-4 (TokenBudget wiring)      ← unblocks spend control
  ↓
IMP-3 (Trigger → Workflow)      ← unblocks automation
  ↓
IMP-5 (SemanticSearch caching)  ← performance fix
  ↓
IMP-6 (StructuredLogger)        ← observability
  ↓
IMP-7 (Graph integration)       ← workflow engine upgrade
  ↓
IMP-8, IMP-9, IMP-10            ← parallel, independent
```

---

## Rules for Claude Code Execution

1. **One task per session.** Do not combine tasks.
2. **Commit after each task.** Message format: `fix(IMP-N): <description>`
3. **Run tests before commit:** `pytest tests/ -x --tb=short -q`
4. **Run lint before commit:** `ruff check . && ruff format --check .`
5. **Do not modify unrelated files.** Stay scoped to the task.
6. **If a test hangs for >30 seconds,** stop and report which test. Do not retry infinitely.
7. **Do not install new pip packages** unless the task explicitly says to (IMP-8 only).
