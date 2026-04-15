# Birkin Roadmap

> This roadmap reflects current priorities and direction. Timelines and scope may shift as we learn from users and contributors.

---

## Phase 1: Foundation (Current)

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
- [x] 99 passing tests (pytest + xdist)
- [x] ruff lint + format clean
- [x] One-click launchers (Birkin.command, start.sh, start.bat)
- [x] Auto-open browser on server start
- [x] .env-based API key management from WebUI
- [x] JSON config persistence (birkin_config.json)

### Phase 1 — Remaining Work
- [x] **Chat bubble streaming fix** — unified SSE queue, proper finalization, no stuck states
- [x] **Error recovery with auto-fallback** — primary provider fails → fallback provider auto-tries
- [ ] **Workflow execution engine** — currently workflows are visual-only; the agent doesn't yet follow user-defined workflow graphs at runtime
- [ ] **Built-in tools** — terminal, web search, file operations, code execution (tool interface exists but no concrete tools yet)
- [ ] **Context compression** for long conversations
- [ ] **Telegram webhook health monitoring** — auto-detect and report failures
- [ ] **WebUI visual regression tests** (Playwright screenshots)
- [ ] **Test coverage** for wiki API and telegram management routes (~99 → ~120 tests)

---

## Phase 2: Polish & Community (Next)

**Goal:** Production-ready experience, contributor-friendly ecosystem.

- [ ] Discord, Slack, WhatsApp messaging adapters
- [ ] Landing page and documentation site
- [ ] Plugin marketplace / community skill registry
- [ ] Skill system (bundled + community skills)
- [ ] Subagent delegation and parallel task execution
- [ ] Scheduled tasks and automation workflows
- [ ] Docker one-command deployment
- [ ] Comprehensive test suite (80%+ coverage)
- [ ] MCP integration

---

## Phase 3: Learning & Intelligence (Planned)

**Goal:** Agents that genuinely improve over time.

- [ ] Built-in skill creation from experience
- [ ] Reinforcement learning training pipeline
- [ ] Trajectory collection and evaluation
- [ ] Multi-agent collaboration patterns
- [ ] Knowledge graph enhancements (semantic search, embeddings)

---

## Phase 4: Enterprise & Security (Planned)

**Goal:** Premium features for teams and businesses.

- [ ] Cybersecurity management harness (vulnerability scanning, threat detection)
- [ ] Team workspaces with role-based access control
- [ ] Analytics dashboard and audit logging
- [ ] Enterprise SSO integration
- [ ] Managed cloud hosting with SLA

---

## How to Influence the Roadmap

- **Feature requests:** Open a [GitHub Issue](https://github.com/ashmoonori-afk/birkin/issues/new)
- **Discussion:** Join [GitHub Discussions](https://github.com/ashmoonori-afk/birkin/discussions)
- **Contribute:** Check issues labeled [`good-first-issue`](https://github.com/ashmoonori-afk/birkin/labels/good-first-issue)

---

*Built in Korea, designed for the world.*
