# Birkin — Development Guide

Instructions for AI coding assistants and human developers working on the birkin codebase.

## Golden Rules

1. **Every new `.py` file needs a test file** — `birkin/foo/bar.py` → `tests/foo/test_bar.py`
2. **Max 400 lines per file** — split before you hit the limit (see `.file-size-exceptions`)
3. **Run before commit** — `ruff check . && ruff format . && pytest --tb=short -q`
4. **No silent failures** — use `ErrorReporter` (`birkin/core/error_reporter.py`) instead of bare `except: pass`
5. **No print() in library code** — use `logging.getLogger(__name__)`

## Project Structure

```
birkin/
├── core/                 # Agent loop, LLM providers, workflow engine
│   ├── agent.py          # Core conversation loop (memory + tools + compression)
│   ├── providers/        # 9 LLM providers (anthropic, openai, gemini, groq, ollama, etc.)
│   ├── graph/            # StateGraph execution engine (conditionals, parallel, loops)
│   ├── workflow/          # NL builder, recommender, feedback loop
│   ├── approval/         # User approval gate for external actions
│   ├── budget/           # Token budget management
│   └── context/          # Context injection + profile management
├── memory/               # Persistent knowledge system
│   ├── wiki.py           # WikiMemory — markdown pages with frontmatter
│   ├── compiler.py       # Session → wiki page compilation
│   ├── classifier.py     # Bilingual (KO/EN) memory classifier
│   ├── semantic_search.py # Embedding-based search
│   ├── audit.py          # Memory audit trail (transparency)
│   ├── event_store.py    # SQLite WAL append-only event store
│   ├── utils.py          # strip_frontmatter, sanitize_content
│   ├── insights/         # Pattern detection engine
│   ├── importers/        # ChatGPT/Claude history import
│   └── embeddings/       # Encoder ABC + vector store (Numpy/FAISS)
├── gateway/              # FastAPI backend
│   ├── app.py            # App factory, lifespan, cron jobs
│   ├── deps.py           # Singleton DI (get/set/reset pattern)
│   ├── routers/          # 18 API routers (chat, workflows, wiki, security, etc.)
│   └── platforms/        # Telegram adapter
├── triggers/             # Cron, file watch, webhook, message triggers
├── skills/               # SKILL.md plugin system + loader + AST sandbox
├── tools/builtins/       # Shell, file ops, web search, wiki read
├── mcp/                  # MCP client + server + browser automation
├── eval/                 # JSONL evaluation framework + recommender eval
├── observability/        # Structured tracing
├── voice/                # Whisper STT + TTS
├── web/static/           # 10-tab WebUI (vanilla JS)
└── tests/                # 724+ tests (pytest, pytest-asyncio, pytest-xdist)
```

## Adding a New Module

1. Create `birkin/yourmodule/yourfile.py`
2. Create `tests/yourmodule/test_yourfile.py` with minimum 3 test cases
3. Keep file under 400 lines
4. Use type hints (Python 3.11+)
5. Add docstring to every public class and function
6. If the module has external side effects (network, disk, LLM), make them injectable

## Memory System Architecture

```
Conversation → EventStore (SQLite WAL)
                    ↓
              MemoryCompiler (LLM classification)
                    ↓
              WikiMemory (markdown pages)
              - entities/   (people, projects, tools)
              - concepts/   (ideas, patterns, knowledge)
              - sessions/   (conversation summaries)
              - workflows/  (automation results)
              - meta/       (feedback, settings)
                    ↓
              SemanticSearch (embeddings)
                    ↓
              build_context() → injected into next session
```

## Security Rules

- Shell commands: allowlist only (`birkin/tools/builtins/shell.py`)
- File writes: restricted to working directory (`file_ops.py` `_resolve_safe_path`)
- Wiki content: sanitized against prompt injection (`memory/utils.py` `sanitize_content`)
- Skills: AST validation before install (`skills/loader.py` `validate_skill_code`)
- External actions: require user approval via `ApprovalGate`

## Anti-Patterns to Avoid

### Silent failure
```python
# BAD
try:
    wiki.ingest(...)
except Exception:
    pass

# GOOD
try:
    wiki.ingest(...)
except Exception as exc:
    logger.warning("Wiki ingest failed: %s", exc)
    if self._error_reporter:
        self._error_reporter.add(ErrorSeverity.WARNING, "memory", "Memory save failed")
```

### God function
```python
# BAD — 200-line function doing 5 things
def process_everything(data): ...

# GOOD — each function does one thing
def validate(data): ...
def parse(validated): ...
def save(transformed): ...
```

### Hardcoded dependencies
```python
# BAD
class Agent:
    def __init__(self):
        self.wiki = WikiMemory("/fixed/path")

# GOOD
class Agent:
    def __init__(self, wiki: WikiMemory | None = None):
        self.wiki = wiki
```

## Lint & Test

```bash
ruff check .              # Lint (C90, B, SIM, UP, RUF, PIE, RET)
ruff check --fix .        # Auto-fix
ruff format .             # Format
pytest --tb=short -q      # Test
bash scripts/check-file-sizes.sh  # File size check
```
