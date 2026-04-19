<p align="center">
<pre align="center">
 ██████╗ ██╗██████╗ ██╗  ██╗██╗███╗   ██╗
 ██╔══██╗██║██╔══██╗██║ ██╔╝██║████╗  ██║
 ██████╔╝██║██████╔╝█████╔╝ ██║██╔██╗ ██║
 ██╔══██╗██║██╔══██╗██╔═██╗ ██║██║╚██╗██║
 ██████╔╝██║██║  ██║██║  ██╗██║██║ ╚████║
 ╚═════╝ ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝
</pre>
  <b>The AI agent that actually remembers you.</b><br>
  Self-hosted · Multi-LLM · Persistent Memory · Workflow Automation
</p>

<p align="center">
  <a href="#-quick-start">Quick Start</a> · <a href="#-why-birkin">Why Birkin</a> · <a href="#-memory-system">Memory</a> · <a href="#-workflow-automation">Automation</a> · <a href="#-architecture">Architecture</a> · <a href="README-ko.md">한국어</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT License" />
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+" />
  <img src="https://img.shields.io/badge/version-v0.8.0-green" alt="v0.8.0" />
  <img src="https://img.shields.io/badge/tests-724%2B-brightgreen" alt="724+ tests" />
  <img src="https://img.shields.io/badge/providers-9-orange" alt="9 Providers" />
</p>

---

> **Every AI tool forgets you the moment the conversation ends.**
> Birkin doesn't. It compiles your conversations into a living wiki,
> detects your patterns, and automates your repetitive work —
> all on your machine, under your control.

<p align="center">
  <img src="docs/screenshots/01-chat.png" width="720" alt="Birkin Chat UI" />
</p>

---

## Why Birkin?

### The Problem

You've used ChatGPT, Claude, Gemini. Every session starts from zero. You re-explain your role, your project, your preferences. Your AI has amnesia.

Self-hosted alternatives like Open WebUI give you a local interface — but the same forgetful brain. And [138 CVEs in 63 days](https://www.horizon3.ai/) later, "self-hosted" doesn't mean "safe" either.

### The Solution

Birkin is a **personal agent OS** that sits on your machine and builds persistent knowledge from every interaction.

| | ChatGPT / Claude | Open WebUI | **Birkin** |
|---|---|---|---|
| Memory | Per-session | Vector search (store & retrieve) | **Compile to wiki** (organize, link, decay) |
| Automation | None | Basic pipelines | **47-node workflow engine** with triggers |
| Learns you | No | No | **Pattern detection → proactive suggestions** |
| Data | Cloud | Local but exposed | **Local, minimal attack surface** |
| Providers | Single | Multi-LLM | **9 providers**, auto-routing |

---

## Key Features

### Memory That Compounds

Birkin doesn't just store conversations — it **compiles** them.

```
Conversation → LLM Classifier → Wiki Pages (entities, concepts, sessions)
                                      ↓
                              [[wikilinks]] connect related knowledge
                                      ↓
                              Decay algorithm: high-value stays, noise fades
                                      ↓
                              Next session: relevant context auto-injected
```

- **Compile, don't dump** — Conversations are distilled into structured wiki pages, not thrown into a vector database
- **Natural forgetting** — 20-day half-life. Frequently referenced knowledge strengthens; unused knowledge fades
- **Bilingual** — Korean and English entity extraction, classification, and search
- **Transparent** — Every memory page shows what it knows, why, and where it came from

### Workflow Automation

Describe what you want in plain language. Birkin builds it.

```
"매일 아침 HN 탑 뉴스 요약해서 텔레그램으로 보내줘"
→ Auto-generates a workflow graph with cron trigger + web scraper + LLM summarizer + Telegram sender
```

- **47 node types** — LLM calls, API requests, conditionals, loops, parallel execution, quality gates
- **4 trigger types** — Cron schedules, file watchers, webhooks, message filters
- **Visual editor** — Drag-and-drop workflow builder in the WebUI
- **Natural language builder** — Describe in Korean or English, get an executable graph

### Multi-Provider Intelligence

One interface. Nine LLM providers. Automatic routing.

| Provider | Strength | Use Case |
|---|---|---|
| Claude | Reasoning, code | Complex analysis |
| GPT-4 | General, tools | Everyday tasks |
| Gemini | Multimodal, 1M context | Long documents |
| Perplexity | Web search | Current events |
| Groq | Ultra-fast inference | Quick responses |
| Ollama | Local, private | Offline use |
| OpenRouter | Model marketplace | Specialized models |

---

## Quick Start

### Option 1: One-Click (Recommended)

**Windows:** Double-click `scripts/start.bat`
**macOS/Linux:** `scripts/start.sh`

Opens at `http://127.0.0.1:8321`. First run takes ~1 minute.

### Option 2: Docker

```bash
git clone https://github.com/ashmoonori-afk/birkin.git && cd birkin
cp .env.example .env   # Add your API keys
docker compose up -d   # → http://localhost:8321
```

### Option 3: Manual

```bash
git clone https://github.com/ashmoonori-afk/birkin.git && cd birkin
python3 -m venv .venv && source .venv/bin/activate
pip install -e "."
birkin                # WebUI at :8321
```

### CLI Commands

```bash
birkin              # Launch WebUI
birkin chat         # Terminal REPL
birkin mcp serve    # MCP server (Claude Code, Cursor, etc.)
birkin eval run     # Run evaluations
birkin skill install <url>  # Install community skills
birkin export       # Backup all data
```

### API Keys

Add to `.env` — only the providers you use:

```bash
ANTHROPIC_API_KEY=sk-ant-...    # Claude
OPENAI_API_KEY=sk-...           # GPT + OpenRouter
GEMINI_API_KEY=...              # Gemini
PERPLEXITY_API_KEY=pplx-...     # Search-augmented
GROQ_API_KEY=gsk_...            # Fast inference
```

---

## Memory System

### How It Works

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│ Conversation │ ──→ │ LLM          │ ──→ │ Wiki Pages      │
│              │     │ Classifier   │     │ - entities/     │
│              │     │ (KO/EN)      │     │ - concepts/     │
│              │     │              │     │ - sessions/     │
└─────────────┘     └──────────────┘     └────────┬────────┘
                                                   │
                    ┌──────────────┐     ┌─────────▼────────┐
                    │ Semantic     │ ←── │ [[wikilinks]]    │
                    │ Search       │     │ + decay scoring  │
                    │              │     │ + confidence     │
                    └──────┬───────┘     └──────────────────┘
                           │
                    ┌──────▼───────┐
                    │ Next Session │
                    │ Context      │
                    │ Injection    │
                    └──────────────┘
```

### Memory Features

- **Relevance-scored injection** — Only related knowledge enters the prompt, saving tokens
- **Natural decay** — 20-day half-life keeps memory fresh
- **Wikilink graph** — Pages connect via `[[links]]`, building a knowledge network
- **Profile compilation** — Import ChatGPT/Claude history to bootstrap your profile
- **Daily compilation** — Cron job at 3 AM distills sessions into permanent knowledge
- **Lazy loading** — Compact index in prompt, `wiki_read` tool fetches full pages on demand

---

## Workflow Automation

### Node Types (47)

| Category | Nodes |
|---|---|
| **AI** | LLM, classifier, embedder, summarizer, translator, knowledge-extract |
| **Tools** | Web search, code execution, API calls, file operations |
| **Control** | Conditions, loops, delays, parallel, merge |
| **Quality** | Code review, human review, guardrails, validators, test runners |
| **I/O** | Input, output, webhook trigger |
| **Platform** | Telegram, email, HackerNews, notifications |

### Triggers

| Type | Example |
|---|---|
| **Cron** | `0 9 * * 1-5` — Every weekday at 9 AM |
| **File Watch** | `*.md` changed in `~/notes/` |
| **Webhook** | POST to `/api/triggers/webhooks/{id}` |
| **Message** | Keyword or pattern in incoming chat |

---

## Architecture

```
birkin/
├── core/           Agent loop, providers, graph engine, approval gates
├── memory/         Wiki, compiler, classifier, semantic search, audit trail
├── gateway/        FastAPI (18 routers, 66 endpoints)
├── triggers/       Cron, file watch, webhook, message
├── skills/         10 built-in skills + AST sandboxing
├── tools/          Shell, file ops, web search, wiki read
├── mcp/            MCP client + server + browser automation
├── eval/           JSONL evaluation framework
├── observability/  Structured tracing (spans, traces)
├── voice/          Whisper STT + TTS
├── web/            10-tab WebUI
└── tests/          724+ tests
```

### Design Principles

1. **Local-first** — SQLite WAL, no network database, data never leaves your machine
2. **Compile over retrieve** — Don't search raw conversations; distill them into structured knowledge
3. **Transparent** — Every memory page shows its source, confidence, and access history
4. **Minimal attack surface** — No marketplace, no WebSocket exposure, allowlisted shell commands

### Security

- **Prompt injection guard** — 9 regex patterns neutralize injected instructions in wiki content
- **Skill sandboxing** — AST static analysis blocks `subprocess`, `eval`, `exec`, `socket` before install
- **Memory audit trail** — Every write/read logged with source, confidence, and reason
- **Self-check endpoint** — `GET /api/security/check` returns verifiable security posture (score + grade)
- **Shell allowlist** — Only safe read-only commands by default; metacharacters rejected
- **Approval gates** — External actions require explicit user approval

---

## Compared To

| Feature | Open WebUI | LobeChat | **Birkin** |
|---|---|---|---|
| Memory | Vector RAG | None | **Compiled wiki + decay** |
| Workflow engine | Pipelines | None | **47-node graph + triggers** |
| Pattern detection | No | No | **Yes** |
| Proactive suggestions | No | No | **Yes** |
| Korean NER | No | No | **Native** |
| Self-hosted security | 138 CVEs (2026 Q1) | Limited | **Minimal surface** |
| Providers | Multi | Multi | **9 + auto-routing** |
| Tests | ~200 | ~100 | **724+** |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

```bash
pip install -e ".[dev]"
pytest                    # Run tests
ruff check . && ruff format --check .  # Lint
```

---

## License

MIT — see [LICENSE](LICENSE).

Built by humans who got tired of re-introducing themselves to their AI.
