<p align="center">
  <strong>Birkin</strong><br>
  <em>AI that works for you, not the other way around.</em>
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> &bull;
  <a href="#features">Features</a> &bull;
  <a href="ROADMAP.md">Roadmap</a> &bull;
  <a href="CONTRIBUTING.md">Contributing</a>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT License"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/version-v0.3.0-green" alt="v0.3.0">
</p>

---

**Birkin** is a personal agent OS — a memory layer and orchestrator sitting on top of multiple LLMs and external agents. Runs locally, scoped per-device. 9-provider multi-LLM routing, MCP client/server, state graph engine, triggers, semantic memory, and a SpaceX-themed 9-tab WebUI.

---

## Features

### WebUI (9-Tab Interface)

| Tab | What It Does |
|-----|-------------|
| **Chat** | SSE streaming chat with real-time token rendering, agentic flow visualization |
| **Workflow** | Drag-and-drop workflow editor — 30+ node types, 10 sample flows |
| **Memory** | Obsidian-style knowledge graph — force-directed canvas, wiki CRUD |
| **Telegram** | Bot setup wizard, webhook management, connection dashboard |
| **Triggers** | Create/manage cron, file watch, webhook, message triggers |
| **Skills** | Browse and toggle installed skills with tool counts |
| **Dashboard** | Token spend, latency stats, error rates, provider breakdown |
| **Approvals** | Review and approve/reject pending agent actions |
| **Insights** | Weekly usage digest, provider distribution, cost tracking |

### Orchestration Core

| Feature | Description |
|---------|-------------|
| **9 LLM providers** | Anthropic, OpenAI, Perplexity (search), Gemini (multimodal), Ollama (local), Groq (low-latency), OpenRouter, Claude CLI, Codex CLI |
| **Capability routing** | Auto-select provider by capability (reasoning, search, code, vision, low-latency) with cost/speed preference |
| **MCP client/server** | Consume external MCP servers + expose Birkin tools/memory as MCP |
| **Skills system** | MCP-native skills with SKILL.md schema, auto-discovery, enable/disable |
| **State graph engine** | Conditional edges, parallel fan-out, loops with guard, SQLite checkpoints |
| **Trigger system** | Cron, file watch, webhook, message triggers with scheduler |
| **Token budget** | Inline enforcement — compress/downgrade/abort when budget exceeded |

### Memory & Intelligence

| Feature | Description |
|---------|-------------|
| **Event store** | SQLite raw event log for every LLM/tool interaction |
| **Memory compiler** | Session/daily compilation from raw events to wiki pages |
| **Semantic search** | Local embeddings (BGE-m3 / hash fallback) + vector store |
| **Context injection** | Auto-inject relevant wiki context into system prompts |
| **Evaluation framework** | JSONL eval datasets, runner, snapshot diff, regression detection |
| **Insights engine** | Weekly digest, pattern detection, usage trends |

### Agent Capabilities

| Feature | Description |
|---------|-------------|
| **Computer use** | Playwright browser automation (navigate, screenshot, click, extract) |
| **Voice I/O** | Whisper STT + OpenAI TTS with API endpoints |
| **Approval gates** | Safety boundary — require user approval before external actions |
| **Command bar** | Natural language intent parsing + routing |
| **Session fork** | Branch conversations from any message |
| **NL workflow builder** | Describe automation in a sentence → generate graph workflow |

### Messaging

| Platform | Status |
|----------|--------|
| **Telegram** | Working — webhook-based, auto-split long messages, session persistence per user |
| **CLI** | Working — `birkin chat` for terminal REPL |
| Discord / Slack / WhatsApp | Planned (Phase 3) |

---

## Quick Start

### One-Click Launch (Easiest)

**macOS:**
1. Download or clone the repository
2. Double-click **`scripts/Birkin.command`** (or run `scripts/start.sh`)
3. Browser opens automatically at `http://127.0.0.1:8321`

**Windows:**
1. Download or clone the repository
2. Double-click **`scripts/start.bat`**
3. Browser opens automatically

**What happens:** The script creates a virtual environment, installs dependencies, starts the WebUI server, and opens your browser. First run takes ~1 minute; subsequent launches are instant.

### Manual Setup

```bash
git clone https://github.com/ashmoonori-afk/birkin.git
cd birkin

python3 -m venv .venv && source .venv/bin/activate
pip install -e "."

# Launch WebUI (default)
birkin

# Or CLI chat
birkin chat
```

### Configuration

Copy `.env.example` to `.env` and add your API key(s):

```bash
cp .env.example .env
# Edit .env — add at least one:
# ANTHROPIC_API_KEY=sk-ant-...
# OPENAI_API_KEY=sk-...
```

Or skip API keys entirely — if you have `claude` or `codex` CLI installed, Birkin can use them directly (select "Claude Code" or "Codex CLI" in the onboarding wizard or settings).

**Requirements:** Python 3.11+

---

## Architecture

```
birkin/
├── core/               # Agent loop, models, session, providers
│   ├── agent.py            # Conversation loop with tool dispatch
│   ├── providers/          # 9 LLM providers + capability routing
│   │   ├── base.py             # Provider ABC, ProviderProfile
│   │   ├── capabilities.py     # Capability enum, ProviderProfile model
│   │   ├── registry.py         # ProviderRegistry + ProviderRouter
│   │   ├── openai_compat.py    # Base class for OpenAI-compatible providers
│   │   ├── anthropic.py, openai.py, perplexity.py, gemini.py, ollama.py, groq.py
│   │   └── local_cli.py        # Claude Code / Codex CLI (streaming)
│   ├── graph/              # State graph execution engine
│   │   ├── engine.py           # StateGraph builder + CompiledGraph executor
│   │   ├── node.py             # GraphNode protocol, FunctionNode
│   │   ├── state.py            # GraphContext (mutable shared state)
│   │   └── checkpoints/        # SQLiteCheckpointer
│   ├── budget/             # Token budget enforcement
│   ├── command/            # NL command parser + router
│   ├── context/            # Context injection + UserProfile
│   ├── approval/           # Approval gates for safe external actions
│   └── workflow/           # NL workflow builder
├── mcp/                # MCP client, server, adapter, registry
│   ├── client.py, server.py, adapter.py, registry.py, transport.py
│   └── servers/            # MCP server implementations
│       └── computer_use/   # Playwright browser automation
├── triggers/           # Cron, file watch, webhook, message triggers
├── skills/             # MCP-native skill system (SKILL.md schema)
├── tools/              # Tool interface, registry, 4 built-in tools
├── memory/             # LLM Wiki + semantic search + event store
│   ├── wiki.py             # Markdown-based knowledge store
│   ├── event_store.py      # SQLite raw event log
│   ├── compiler.py         # Event → wiki compilation
│   ├── semantic_search.py  # Embedding-based search
│   ├── embeddings/         # Encoder ABC + vector store
│   └── insights/           # Weekly digest, pattern detection
├── eval/               # Evaluation framework (JSONL datasets, runner)
├── observability/      # Structured tracing (Trace, Span, JSONL storage)
├── voice/              # STT (Whisper) + TTS
├── gateway/            # FastAPI backend (15 routers)
├── cli/                # CLI: chat, serve, mcp serve
├── web/static/         # WebUI (9-tab SPA, SpaceX dark theme)
├── tests/              # 461+ tests (pytest)
└── docs/               # Archive, site
```

---

## API Endpoints

| Group | Method | Path | Description |
|-------|--------|------|-------------|
| Chat | POST | `/api/chat`, `/api/chat/stream` | Blocking + SSE streaming chat |
| Sessions | GET/POST/DELETE | `/api/sessions` | Session CRUD |
| Settings | GET/PUT | `/api/settings` | Config + API keys + providers |
| Workflows | GET/PUT/DELETE | `/api/workflows` | Workflow CRUD |
| Wiki | GET/PUT/DELETE | `/api/wiki/pages`, `/api/wiki/graph` | Wiki CRUD + graph |
| Telegram | GET/POST/DELETE | `/api/telegram/*` | Bot + webhook management |
| **Triggers** | GET/POST/DELETE | `/api/triggers` | Trigger CRUD + manual fire |
| **Skills** | GET/POST | `/api/skills` | List + toggle skills |
| **Dashboard** | GET | `/api/observability/spend,latency,errors` | Token spend, latency, errors |
| **Traces** | GET | `/api/traces` | Structured trace data |
| **Approvals** | GET/POST | `/api/approvals` | Pending actions + approve/reject |
| **Voice** | POST | `/api/voice/stt`, `/api/voice/tts` | Speech-to-text + text-to-speech |
| Health | GET | `/api/health` | Health check |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide.

```bash
# Run tests
pytest tests/ -q

# Lint
ruff check .
ruff format --check .
```

---

## Security Model

The Shell tool uses an **allowlist** (not a sandbox) to restrict which commands the LLM may execute. Only a small set of read-only commands (`ls`, `cat`, `grep`, `git`, `find`, etc.) are permitted by default. Shell metacharacters (`|`, `&&`, `>`, `` ` ``, `$(`, etc.) are rejected outright to prevent chaining or redirection.

- **Extend the allowlist** by setting `BIRKIN_SHELL_ALLOWLIST=curl,python` (comma-separated) in your environment.
- **Bypass the allowlist** (development only) with `BIRKIN_SHELL_SANDBOX=off`. A legacy blocklist still catches catastrophic patterns (`rm -rf /`, `sudo`, etc.) as defense-in-depth.
- **LLM-generated commands are code execution.** Deploy Birkin only in trusted environments.
- **Do not expose the API to the public internet** without setting `BIRKIN_AUTH_TOKEN`.

---

## License

MIT — see [LICENSE](LICENSE) for details.

Copyright (c) 2026 Birkin Team.
