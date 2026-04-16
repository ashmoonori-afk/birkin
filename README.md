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
  <img src="https://img.shields.io/badge/version-v0.2.0-green" alt="v0.2.0">
</p>

---

**Birkin** is a self-hosted AI agent platform with a visual WebUI. Chat with AI, design workflows, manage memory, and connect Telegram — all from a cinematic dark-themed interface. Phase 1 complete, Phase 2 (MCP agent runtime) in progress.

---

## Features

### WebUI (4-Tab Interface)

| Tab | What It Does |
|-----|-------------|
| **Chat** | SSE streaming chat with real-time token rendering, agentic flow visualization (tool calls, thinking indicator) |
| **Workflow** | Drag-and-drop workflow editor — 30+ node types, 10 sample flows, activate workflows for chat |
| **Memory** | Obsidian-style knowledge graph — force-directed canvas, view/edit/search wiki pages, orphan detection |
| **Telegram** | Step-by-step bot setup wizard, webhook management, connection status dashboard |

### Core

| Feature | Description |
|---------|-------------|
| **Multi-provider** | Anthropic Claude, OpenAI GPT, Claude Code CLI, Codex CLI — switch providers from the settings panel |
| **Local CLI support** | Use `claude` or `codex` CLI without API keys — real-time stdout streaming |
| **Session persistence** | SQLite-backed conversation history with full session management |
| **LLM Wiki Memory** | Markdown-based persistent knowledge store — agents remember across sessions |
| **Tool system** | Abstract tool interface with registry, loader, and provider-agnostic schema export |
| **Fallback chain** | Configure a fallback provider if the primary one fails |
| **i18n** | Korean + English UI — toggle instantly from the topbar |
| **Onboarding** | First-launch wizard auto-detects available providers and guides setup |

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
2. Double-click **`Birkin.command`** (or `start.sh`)
3. Browser opens automatically at `http://127.0.0.1:8321`

**Windows:**
1. Download or clone the repository
2. Double-click **`start.bat`**
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
│   ├── workflow_engine.py  # Workflow graph execution engine (30+ node types)
│   ├── session.py          # SQLite session persistence (WAL mode)
│   ├── models.py           # Message, ToolCall, ToolResult dataclasses
│   ├── errors.py           # Error hierarchy (BirkinError → ProviderError)
│   ├── defaults.py         # System prompt (Karpathy guidelines)
│   └── providers/          # LLM provider abstraction
│       ├── base.py     # Provider ABC, ProviderResponse, TokenUsage
│       ├── anthropic.py # Anthropic Messages API
│       ├── openai.py   # OpenAI Chat Completions (+ OpenRouter)
│       └── local_cli.py # Claude Code / Codex CLI (streaming)
├── tools/              # Tool interface, registry, 4 built-in tools
│   └── builtins/       # shell, web_search, file_read, file_write
├── memory/             # LLM Wiki — markdown-based knowledge store
├── gateway/            # FastAPI backend
│   ├── app.py          # Application factory
│   ├── routes.py       # API routes (chat, SSE, sessions, wiki, telegram, workflows, settings)
│   ├── config.py       # JSON config persistence
│   ├── workflows.py    # Workflow definitions + 10 samples
│   ├── dispatcher.py   # Platform message routing
│   └── platforms/      # Telegram adapter + schemas
├── cli/                # CLI entry point (chat REPL, serve)
├── web/static/         # WebUI (vanilla JS, SpaceX dark theme)
│   ├── index.html      # 4-tab SPA shell
│   ├── style.css       # SpaceX cinematic dark design system
│   ├── i18n.js         # Korean/English translations (185+ keys)
│   ├── app.js          # Chat, settings, onboarding, view router
│   ├── workflow.js     # Drag-and-drop workflow editor
│   ├── memory.js       # Force-directed wiki graph
│   └── telegram.js     # Telegram setup wizard + dashboard
└── tests/              # 215+ tests (pytest)
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/chat` | Send message, get reply (blocking) |
| POST | `/api/chat/stream` | SSE streaming chat |
| GET | `/api/sessions` | List all sessions |
| POST | `/api/sessions` | Create new session |
| GET | `/api/sessions/{id}` | Get session with messages |
| DELETE | `/api/sessions/{id}` | Delete session |
| GET/PUT | `/api/settings` | Read/write config |
| PUT | `/api/settings/keys` | Save API keys to .env |
| GET | `/api/settings/providers` | Detect available providers |
| GET/PUT/DELETE | `/api/workflows` | Workflow CRUD |
| GET | `/api/wiki/pages` | List wiki pages |
| GET/PUT/DELETE | `/api/wiki/pages/{cat}/{slug}` | Wiki page CRUD |
| GET | `/api/wiki/graph` | Node-link graph data |
| GET | `/api/wiki/search?q=` | Search wiki |
| GET | `/api/telegram/status` | Bot + webhook status |
| POST/DELETE | `/api/telegram/webhook` | Webhook management |
| POST | `/api/webhooks/telegram/{token}` | Telegram webhook receiver |
| GET | `/api/health` | Health check |

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
