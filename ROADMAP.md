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

## Phase 3: Measure, Loop, Onboard (Complete, v0.4.0)

**Goal:** Close the gap between "modules exist" and "the product delivers measurable value." Phase 2 built the parts; Phase 3 wires them end-to-end, proves they work with real data, and makes the first-run experience undeniable.

**North Star score:** 53.5 → **87.5 (A-)**. Target achieved.

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

### Sprint 3B — End-to-End Automation (Complete)

- [x] **NL workflow builder LLM upgrade** — LLM structured output with 33 valid node types, Korean/English support, keyword fallback
- [x] **E2E demo workflow** — "HackerNews daily to Telegram" (hn-fetch → summarizer → telegram-send), 11th sample workflow
- [x] **Eval CLI + baseline dataset** — `birkin eval run/list/diff` CLI, 10-case baseline dataset (factual, code, KO, reasoning)
- [x] **Memory-aware eval** — `--memory` flag, isolated temp WikiMemory per case, 10-case memory-recall dataset
- [x] **Insights engine → API + scheduled** — `GET /api/insights/weekly,patterns,trend`, InsightsEngine singleton, Sunday auto-digest

### Sprint 3D — Onboarding & Deployment (Complete)

- [x] **First-run "wow" experience** — Guided prompt banner after onboarding, auto-create HN workflow + cron trigger, success/info toast
- [x] **Dashboard "prove it" metrics** — 3 hero cards (tokens saved, automations run, memory pages), `GET /api/observability/hero`
- [x] **Docker one-command deployment** — Dockerfile, docker-compose.yml, QUICKSTART.md, env var configurable paths
- [x] **birkin export/import** — Encrypted zip backup (Fernet, optional cryptography dep), `birkin export/import` CLI
- [x] **Skill install CLI + community registry** — `birkin skill install/list/remove`, path traversal protection, SKILL-AUTHORING.md

### Phase 3 — Final Score

| Sprint | Tasks | Score Impact | Running Total | Status |
|--------|-------|-------------|---------------|--------|
| 3A (Wire & Measure) | 5 | +17 | 70.5 | **Complete** |
| 3B (E2E Automation) | 5 | +12 | 82.5 | **Complete** |
| 3D (Onboarding & Deploy) | 5 | +5 | 87.5 | **Complete** |

**Total: 15 tasks completed. Tests: 395 → 502 (+107). Score: 87.5 (A-)**

---

## Phase 4: Hardening & Polish (Complete, v0.5.3)

**Goal:** Fix every bug found via smoke testing, improve SSE chat quality, harden the workflow engine, modernize the UI, and achieve 607+ test coverage.

**Tests: 502 → 607 (+105). 14 releases (v0.4.1 → v0.5.3).**

### Sprint 4A — Critical Bug Fixes (v0.4.1 → v0.4.7)

- [x] **SSE chat bubble not rendering** — `workflow.onEvent` undefined crashed all SSE event processing silently (v0.4.1)
- [x] **Memory not saving conversations** — `stream()` missing `_auto_save_memory()`, Korean signals absent, slug generation broken for Korean, decay defaults wrong (v0.4.2)
- [x] **Workflow node ID collision** — `nodeIdCounter = nodes.length` instead of max ID; edge metadata loss on save; condition routing not implemented (v0.4.3)
- [x] **Memory decay feedback loop broken** — `build_context()` never called `touch_page()`; `touch_page()` silently failed on pages without frontmatter (v0.4.4)
- [x] **Skill toggle not persisted** — enable/disable lost on restart; dispatcher missing skill tools for Telegram (v0.4.5)
- [x] **Telegram polling crash on ProviderError** — `BirkinError` not caught; health check auto-restart didn't set `_polling_active` (v0.4.6)
- [x] **Trigger CRUD not persisted** — create/delete only in-memory, lost on restart; frontend JSON parse crash (v0.4.7)

### Sprint 4B — Code Quality & Security (v0.4.8)

- [x] **XSS vulnerability** — triggers.js and skills.js rendered server data in innerHTML without escaping → `esc()` + DOM event listeners
- [x] **Spaghetti code cleanup** — frontmatter parsing 5x duplication → `_parse_frontmatter()` helper; signals lists rebuilt per call → class frozenset constants; deferred imports → module-level; TriggerStore → context manager; timezone naive/aware mismatch → UTC unified

### Sprint 4C — SSE Chat Quality (v0.4.9)

- [x] **Event-driven queue** — replaced 50ms polling with `asyncio.wait` (zero-delay, zero-loss)
- [x] **Network error retry** — partial response preserved + Retry button
- [x] **md() rendering throttle** — rAF batching (1 render/frame, prevents O(n²) jank)
- [x] **Scroll-lock** — auto-scroll stops when user scrolls up 150px+
- [x] **Accessibility** — aria-live on thinking/writing indicators, aria-hidden on cursor, prefers-reduced-motion

### Sprint 4D — Workflow Engine (v0.5.0 → v0.5.1)

- [x] **Loop convergence** — early exit on 2x consecutive identical output (saves LLM tokens)
- [x] **LLM timeout** — `asyncio.wait_for` with 120s default; fallback on timeout; per-node configurable
- [x] **Error recovery paths** — `ERROR` label edges route to recovery nodes instead of breaking workflow
- [x] **True parallel execution** — `asyncio.gather` on parallel node children; merge node collects outputs
- [x] **37 handler unit tests** — LLM, classifier, loop, condition, guardrail, validator, memory, parallel/merge, timeout, error recovery
- [x] **workflow.js module split** — 933-line monolith → 5 files (state, canvas, events, config, main)

### Sprint 4E — UI & E2E (v0.5.2 → v0.5.3)

- [x] **Browser E2E smoke test** — 22 steps via Playwright MCP across all 9 views + mobile
- [x] **Trigger form reset bug** — form retained previous values on reopen
- [x] **Elapsed time indicator** — thinking indicator shows seconds ("Reasoning... (15s)")
- [x] **Layout overhaul** — removed `max-width: 720px` dead space; persistent sidebar on 1024px+
- [x] **4-tier responsive** — 480 / 768 / 1024 / 1440px breakpoints with adaptive spacing
- [x] **Language dropdown** — EN/KO toggle → extensible dropdown with LANG_META system; aria-haspopup + listbox accessibility
- [x] **4px spacing scale** — CSS custom properties (--sp-1 through --sp-10) per ui-ux-pro-max guidelines

### Phase 4 — Summary

| Sprint | Releases | Tests Added | Key Impact |
|--------|----------|-------------|------------|
| 4A (Bug Fixes) | v0.4.1–v0.4.7 | +4 | 7 critical bugs across all subsystems |
| 4B (Code Quality) | v0.4.8 | +0 | XSS fix, 5x code dedup, timezone fix |
| 4C (SSE Quality) | v0.4.9 | +0 | Chat reliability 6→8, latency 7→9 |
| 4D (Workflow Engine) | v0.5.0–v0.5.1 | +37 | Parallel exec, error recovery, 37 tests |
| 4E (UI & E2E) | v0.5.2–v0.5.3 | +0 | Responsive layout, language dropdown |

---

## Phase 5: Future (Deferred)

Monetization and business-model decisions are intentionally deferred. Birkin stays focused on a single-user, self-hosted, open-source experience.

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