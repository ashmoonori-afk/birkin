# Birkin Roadmap

> This roadmap reflects current priorities and direction. Timelines and scope may shift as we learn from users and contributors.

---

## Vision

Birkin exists to deliver three outcomes for its user:

1. **Token savings (토큰 절약)** — smart context compression, memory compilation, local models, and cheap-model routing so the user spends less per outcome.
2. **Work automation (업무 자동화)** — scheduled tasks, event-driven triggers, and computer use so the agent executes real work without supervision.
3. **Personalized evolution (개인 맞춤 진화)** — persistent memory, trajectory collection, and evaluation loops so the agent gets better at *your* work over time.

Every Phase 2 item below maps back to at least one of these three.

---

## Phase 1: Foundation (Complete)

**Goal:** Stable, self-hostable AI agent with visual WebUI and messaging integration.

### Core Agent
- [x] Core agent loop with multi-turn conversation
- [x] Provider abstraction (Anthropic, OpenAI, OpenRouter)
- [x] Local CLI providers (Claude Code, Codex) — no API key required
- [x] Real-time stdout streaming for CLI providers
- [x] Session persistence (SQLite with WAL mode)
- [x] Conversation context passed to CLI providers
- [x] Tool interface with registry and dynamic loader
- [x] System prompt customization (Karpathy guidelines default)
- [x] Fallback provider chain

### WebUI
- [x] SpaceX-inspired dark cinematic design system
- [x] SSE streaming chat with token-by-token rendering
- [x] Agentic flow visualization (tool calls, thinking indicator)
- [x] 4-tab navigation (Chat, Workflow, Memory, Telegram)
- [x] Settings panel (provider, API keys, model, fallback, system prompt)
- [x] Onboarding wizard with provider auto-detection
- [x] Korean/English i18n (185+ translated strings)

### Workflow Editor
- [x] Drag-and-drop canvas with pan/zoom
- [x] 30+ node types across 7 categories (I/O, AI, Tools, Memory, Control, Gates, Platform)
- [x] Node connection via port dragging (bezier curves)
- [x] Node configuration panel (label, provider, template, etc.)
- [x] 10 sample workflows (Code Review Gate, RAG Pipeline, etc.)
- [x] Sample gallery on first visit
- [x] Save/load workflows via API
- [x] Activate workflow for chat sessions
- [x] Chat-based workflow recommendation (keyword detection)

### Memory (LLM Wiki)
- [x] Markdown-based persistent knowledge store
- [x] Categories: entities, concepts, sessions
- [x] Wikilink cross-references with lint (broken links, orphans)
- [x] Force-directed graph visualization (Obsidian-style)
- [x] View/edit/delete pages from graph UI
- [x] Search across memory
- [x] Memory context injection into system prompt
- [x] Wiki CRUD API

### Telegram
- [x] Webhook-based bot integration
- [x] Polling mode (no public URL needed — one-click start)
- [x] Step-by-step setup wizard in WebUI (BotFather guide → token → polling/webhook)
- [x] Session persistence per Telegram user
- [x] Auto-split long messages (4096 char limit)
- [x] Connection status dashboard with polling start/stop
- [x] Config-based provider selection (not hardcoded)

### Infrastructure
- [x] 215+ passing tests (pytest)
- [x] ruff lint + format clean
- [x] One-click launchers (scripts/Birkin.command, scripts/start.sh, scripts/start.bat)
- [x] Auto-open browser on server start
- [x] .env-based API key management from WebUI
- [x] JSON config persistence (birkin_config.json)

### Phase 1 — Completed Sprint
- [x] **Chat bubble streaming fix** — unified SSE queue, proper finalization, no stuck states
- [x] **Error recovery with auto-fallback** — primary provider fails → fallback provider auto-tries
- [x] **Built-in tools** — shell, web search, file read/write (4 tools with security checks)
- [x] **Context compression** — auto-compress conversations over 20 messages with LLM summarization
- [x] **Test coverage** — 99 → 206 tests (wiki API, telegram management, workflow routes, auth, compression, shell)
- [x] **Static files fix** — mount under /static to prevent 405 on API POST routes

### Phase 1 — Final Sprint
- [x] **Workflow execution engine** — BFS graph traversal, 30 node type handlers with real tool/memory/API execution, fallback provider
- [x] **Telegram health monitoring** — 60s background check, auto-restart crashed polling, webhook error detection
- [x] **Code review cleanup** — dead code removal, god function refactoring, duplicate consolidation, version centralization
- [x] **CLI prompt optimization** — reduced prompt size for 3-10x faster telegram responses
- [x] **Security hardening** — Bearer token auth middleware, shell tool allowlist, Telegram webhook secret_token verification
- [x] **Anthropic model IDs** — updated to claude-opus-4-6, claude-sonnet-4-6, claude-haiku-4-5
- [x] **SQLite lifespan** — proper FastAPI lifespan with clean shutdown and WAL lock cleanup
- [x] **Router modularization** — split 1004-line routes.py into 10 focused router modules
- [x] **Async chat endpoint** — non-blocking /api/chat with await agent.achat()
- [x] **ThreadPoolExecutor reuse** — shared 4-worker pool instead of per-call thread creation
- [x] **LLM memory classifier** — bilingual (KO+EN) auto-categorization replacing English-only heuristics
- [ ] **WebUI visual regression tests** (Playwright screenshots) — deferred to Phase 2

---

## Phase 2: Agent Runtime (Complete, v0.3.0)

**Goal:** Turn Birkin from a chat UI with tools into a personal agent OS — MCP-compatible, schedulable, observable, and capable of executing real work.

### Sprint 0 — Debt Cleanup (Complete)

- [x] **Exception narrowing** — replaced 22 bare `except Exception` with specific types
- [x] **Config validation** — Pydantic schema validation for birkin_config.json
- [x] **Concurrency locks** — asyncio locks on WikiMemory and Telegram polling
- [x] **Return type annotations** — wiki and workflows routers fully typed
- [x] **Test hardening** — 215+ tests passing

### Phase 2A — Orchestration Core (Complete)

- [x] **Multi-LLM connector** — 9 providers (Anthropic, OpenAI, Perplexity, Gemini, Ollama, Groq, OpenRouter, Claude CLI, Codex CLI) with capability metadata and auto-routing
- [x] **MCP client & server** — consume external MCP servers, expose Birkin tools/memory as MCP. `birkin mcp serve` CLI command
- [x] **Skills system (MCP-native)** — SKILL.md schema, auto-discovery, enable/disable. 2 bundled skills (code-review, web-summarizer)
- [x] **State graph execution engine** — conditional edges, parallel fan-out, loops with guard, SQLite checkpoints. Coexists with BFS simple mode
- [x] **Trigger abstraction** — cron, file watch, webhook, message triggers with scheduler
- [x] **Token budget manager** — inline enforcement (compress/downgrade/abort per policy)
- [x] **Evaluation framework** — JSONL datasets, runner, storage, snapshot diff
- [x] **Observability logging** — structured traces (Trace → Span), JSONL storage, API

### Phase 2B — Agent Capabilities (Complete)

- [x] **Computer Use (Playwright)** — 6 browser tools (navigate, screenshot, click, type, extract, wait)
- [x] **Voice I/O** — Whisper STT + OpenAI TTS with API endpoints
- [x] **Semantic memory** — local embeddings (BGE-m3 / hash fallback), vector store, semantic search
- [x] **Context injection** — auto-inject relevant wiki context via semantic search + UserProfile
- [x] **Approval gates** — safety boundary for external actions with async wait + timeout
- [x] **Memory compiler** — raw event log → compiled wiki pages (session/daily)

### Phase 2C — UX & Intelligence (Complete)

- [x] **Command bar** — natural language intent parsing + routing
- [x] **Session fork** — branch conversations from any message
- [x] **Observability dashboard** — token spend, latency stats, error rates via API
- [x] **NL workflow builder** — describe automation → generate graph workflow
- [x] **Insights engine** — weekly digest, pattern detection, usage trends
- [x] **WebUI integration** — 5 new tabs (Triggers, Skills, Dashboard, Approvals, Insights) with SpaceX dark theme

### Phase 2 — Discovery track

- [x] File upload to memory
- [x] Smart memory categorization (LLM-based)
- [x] `@memory` search command in chat
- [ ] Auto wikilink detection
- [ ] Session summarization (scheduled via triggers)

---

## Phase 3: Measure, Loop, Onboard (In Progress)

**Goal:** Close the gap between "modules exist" and "the product delivers measurable value." Phase 2 built the parts; Phase 3 wires them end-to-end, proves they work with real data, and makes the first-run experience undeniable.

**North Star score:** 53.5 → **73 (B)** after wiring sprint. Target: 85 (A-).

### Sprint 3A — Wire & Measure (Complete)

- [x] **MCP + Skills → Agent gateway** — shared singletons in deps.py, skill tools + mcp_registry passed to Agent
- [x] **ProviderRouter → auto-routing** — `provider: "auto"` selects cheapest available provider
- [x] **TokenBudget → Agent run loop** — check_before_call + record_usage on every turn
- [x] **StructuredLogger → Agent** — Trace + Span per LLM call and tool execution, JSONL storage
- [x] **SemanticSearch caching** — skip re-index when page count unchanged
- [x] **Trigger → Workflow execution** — noop callback replaced with real WorkflowEngine.execute()
- [x] **Trigger persistence** — SQLite TriggerStore survives restart
- [x] **Graph ↔ WorkflowEngine** — mode='graph' delegates to StateGraph engine
- [x] **sentence-transformers optional** — auto-detect, fallback to hash encoder
- [x] **Memory improvements** — relevance scoring, decay, poisoning protection, Korean NER, aliases, wiki_read tool

### Sprint 3B — End-to-End Automation (Next)

- [ ] **NL workflow builder LLM upgrade** — replace keyword parser with LLM structured output
- [ ] **E2E demo workflow** — "HackerNews daily to Telegram" (CronTrigger → web_search → summarize → send)
- [ ] **Memory flywheel instrumentation** — trace spans for memory ops, weekly health metric
- [ ] **P3-3C-3: Eval CLI + baseline dataset** — Add `birkin eval run <dataset.jsonl> --provider anthropic` subcommand to `cli/main.py`. Create `eval/datasets/baseline-10.jsonl` with 10 diverse test cases (factual recall, Korean, code, summarization). Run baseline eval, save results as `eval/results/baseline.jsonl`. Add `birkin eval diff <baseline> <current>` for regression detection. *(Files: `cli/main.py`, new `eval/datasets/baseline-10.jsonl`, `eval/runner.py`)*
- [ ] **P3-3C-4: Memory-aware eval** — Create `eval/datasets/memory-recall-10.jsonl` with 10 cases that require information from previous sessions (e.g., "What was my API key provider last week?"). Run eval with memory ON vs OFF. The score delta proves the flywheel works. Document results in `eval/results/memory-impact.md`. *(Files: new `eval/datasets/memory-recall-10.jsonl`, new `eval/results/memory-impact.md`)*
- [ ] **P3-3C-5: Insights engine → API + scheduled generation** — `InsightsEngine` (`memory/insights/engine.py` lines 39–170) has `weekly_digest()`, `identify_patterns()`, and `usage_trend()` but is orphaned. Create `gateway/routers/insights.py` with `GET /api/insights/weekly`, `GET /api/insights/patterns`, `GET /api/insights/trend`. Schedule weekly digest generation in `_daily_memory_loop()` on Sundays. *(Files: new `gateway/routers/insights.py`, `gateway/app.py`)*

### Sprint 3D — Onboarding & Deployment (est. 3 days)

> New user gets value in 5 minutes. Deployable anywhere with one command.

- [ ] **P3-3D-1: First-run "wow" experience** — Detect first launch (onboarding_complete == false). Show a guided prompt: "Try saying: 매일 아침 8시에 뉴스 요약해서 텔레그램으로 보내줘". If Telegram is configured, auto-create the HN daily workflow from P3-3B-5. Show a success toast: "Your first automation is live. Check Telegram tomorrow at 8 AM." *(Files: `web/static/app.js` onboarding section, `gateway/routers/chat.py`)*
- [ ] **P3-3D-2: Dashboard "prove it" metrics** — On the observability dashboard tab, show three hero numbers: (1) tokens saved this week (context injection savings vs full dump), (2) automations run (trigger fire count), (3) memory pages (total + this week delta). These prove the three North Stars. *(Files: `web/static/app.js` dashboard section, `gateway/routers/observability.py`)*
- [ ] **P3-3D-3: Docker one-command deployment** — Create `Dockerfile` (Python 3.11-slim, pip install, uvicorn) and `docker-compose.yml` (app + volume mounts for memory/sessions/config). Add `QUICKSTART.md` with `docker compose up` instructions. Verify .env injection works. *(Files: new `Dockerfile`, new `docker-compose.yml`, new `QUICKSTART.md`)*
- [ ] **P3-3D-4: birkin export/import** — Add `birkin export` CLI command: creates encrypted zip of sessions DB, wiki pages, config, traces. Add `birkin import <archive.zip>`: restores everything. Uses `zipfile` + `cryptography.fernet` (optional dep). *(Files: `cli/main.py`, new `cli/backup.py`)*
- [ ] **P3-3D-5: Skill install CLI + community registry** — Add `birkin skill install <git-url>` that clones a skill repo into `skills/` directory and loads it. Add `birkin skill list` to show installed skills. Create `SKILL-AUTHORING.md` guide for community contributors. This is the seed for an ecosystem. *(Files: `cli/main.py`, `skills/loader.py`, new `docs/SKILL-AUTHORING.md`)*

### Phase 3 — Score Projection

| Sprint | Tasks | Score Impact | Running Total |
|--------|-------|-------------|---------------|
| 3A (Wire & Measure) | 5 | +17 | 70.5 |
| 3B (E2E Automation) | 5 | +12 | 82.5 |
| 3C (Memory Flywheel) | 5 | +8 | 90.5 |
| 3D (Onboarding & Deploy) | 5 | +5 | 95.5 |

**Total: 20 tasks, ~14 days, projected score 85+ (A-)**

---

## Phase 4: Future (Deferred)

Monetization and business-model decisions are intentionally deferred. Birkin stays focused on a single-user, self-hosted, open-source experience through Phase 3.

### Out of scope (by design)

- Multi-user workspaces / team collaboration
- Role-based access control (RBAC)
- SSO / enterprise identity
- Managed cloud hosting
- Multi-tenant billing

These may be revisited if the project's direction changes, but they are explicitly excluded from current planning to keep scope tight.

---

## How to Influence the Roadmap

- **Feature requests & ideas** — [open a GitHub Issue](https://github.com/ashmoonori-afk/birkin/issues)
- **Bug reports** — [open a GitHub Issue](https://github.com/ashmoonori-afk/birkin/issues) with reproduction steps
- **Pull requests welcome** — especially for Phase 3 sprint items

---

*Built in Korea, designed for the world.* 🇰🇷