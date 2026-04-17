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
- [x] 206 passing tests (pytest + xdist)
- [x] ruff lint + format clean
- [x] One-click launchers (Birkin.command, start.sh, start.bat, start.exe)
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

## Phase 2: Agent Runtime (In Progress)

**Goal:** Turn Birkin from a chat UI with tools into a programmable agent runtime — MCP-compatible, schedulable, observable, and capable of executing real work.

**Ordering principle:** MCP first. Every later item (skills, tools, computer use, evaluation) sits on top of the MCP layer, so getting that boundary right unblocks everything else.

### Phase 2A — Runtime Core (MCP First)

- [ ] **MCP client & server support** — first-class Model Context Protocol integration. Existing `Tool` ABC becomes a thin adapter over MCP. Birkin can consume any MCP server and expose its own capabilities as one.
- [ ] **Skills system (MCP-native)** — bundled + community skills packaged as MCP servers. Skill layout = `SKILL.md` + resources, discoverable via registry.
- [ ] **State graph execution engine** — LangGraph-style state machine for workflows. Coexists with the current BFS `simple` mode; new `graph` mode supports conditionals, loops, parallel fan-out, and checkpoints. Existing 10 sample flows migrate gradually.
- [ ] **Trigger abstraction + Cron** — workflows are fired by triggers, not just manual input. Triggers include time (cron), file change, webhook, incoming message, and custom events. Cron is one trigger implementation among many.
- [ ] **Evaluation framework** — fixed question sets with snapshot diff, per-provider latency, token/cost tracking. Outputs JSONL for regression analysis. Feeds the Observability dashboard.
- [ ] **Observability logging** — structured traces for every turn: provider, tokens in/out, tool calls, latency, outcome. Same data source as Evaluation.

### Phase 2B — Agent Capabilities

- [ ] **Computer Use (Playwright MCP)** — headless browser automation delivered as an MCP server. Unlocks "monitor site → summarize → notify" class of workflows. Runs locally to preserve the self-hosted ethos.
- [ ] **Voice I/O** — Whisper STT for input, TTS for output. Integrated in WebUI (mic button) and Telegram (voice messages in, voice replies out). Leverages the project's Korean-language strength.
- [ ] **Semantic memory (local embeddings)** — offline embedding via sentence-transformers or BGE-m3. Zero-dependency semantic search over wiki. Pulled forward from Phase 3 because it directly serves the token-savings and personalization goals.

### Phase 2C — UX & Intelligence

- [ ] **Session fork & replay** — branch a conversation from any message; re-run from an edited past turn. SQLite schema adds `parent_session_id` + `fork_from_seq`. Power-user / prompt-engineering feature.
- [ ] **Observability dashboard** — new tab surfacing token spend, per-session latency, tool failure rate, and cron job history. Reads the Phase 2A telemetry.
- [ ] **Natural language workflow builder** — describe an automation in a sentence → generate the node graph. Depends on stabilized state-graph schema from 2A.

### Phase 2 — Discovery track (parallel, mostly done)

- [x] File upload to memory
- [x] Smart memory categorization (LLM-based)
- [ ] Auto wikilink detection
- [ ] Session summarization (scheduled via Phase 2A triggers)
- [x] `@memory` search command in chat

---

## Phase 3: Ecosystem & Learning

**Goal:** Expand the surface area of what Birkin can automate, and what it can learn from the work it has already done.

### Platform breadth

- [ ] **Ollama first-class provider** — direct REST integration. Completes the "zero API key, fully local" story.
- [ ] **Email adapter (IMAP/SMTP)** — inbox summarization, draft replies, auto-triage. Natural pair with Phase 2A scheduling.
- [ ] **RSS / web change monitor** — register feeds or URLs; fire workflows on change.
- [ ] **Discord, Slack, WhatsApp adapters** — same pattern as Telegram, one at a time.
- [ ] **Desktop notifications** — beyond Telegram.

### Intelligence

- [ ] **Artifacts (inline canvas)** — editable code/doc/diagram panel. Builds on the existing workflow canvas engine.
- [ ] **Memory auto-consolidation (scheduled)** — weekly pass to merge duplicates, update stale entries, and summarize old session pages in the wiki.
- [ ] **Trajectory collection** — export (conversation, outcome) pairs as datasets for DPO / preference learning. No training pipeline in-house; emit data in a standard format.
- [ ] **Knowledge graph enhancements** — semantic search upgrades, cross-reference scoring, entity linking.
- [ ] **Multi-agent / sub-agent delegation** — parallel task execution, sub-agent handoff.

### Operability

- [ ] **Docker one-command deployment**
- [ ] **Encrypted backup/export** — `birkin export` to single encrypted archive (sessions + wiki + config).
- [ ] **Plugin marketplace / community skill registry** (MCP-native).
- [ ] **Playwright visual regression tests** for WebUI.
- [ ] **Landing page and documentation site**.

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