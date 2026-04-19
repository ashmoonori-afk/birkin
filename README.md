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
  <a href="#-memory">Memory</a> · <a href="#-workflows">Workflows</a> · <a href="#-quick-start">Quick Start</a> · <a href="#-security">Security</a> · <a href="#-architecture">Architecture</a> · <a href="README-ko.md">한국어</a>
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
> detects your patterns, and builds workflows to automate your repetitive work —
> all on your machine, under your control.

<p align="center">
  <img src="docs/screenshots/01-chat.png" width="720" alt="Birkin Chat UI" />
</p>

---

## The Two Pillars

Birkin does two things other AI tools don't:

| | What others do | What Birkin does |
|---|---|---|
| **Memory** | Forget after session / dump into vector DB | **Compile into linked wiki** — organized, decaying, transparent |
| **Workflows** | Nothing / basic pipelines | **47-node graph engine** — triggers, parallel exec, quality gates |

Everything else — 9 LLM providers, 10 skills, visual editor, Telegram bot — exists to serve these two.

---

## Memory

### The Problem with RAG

Vector databases store everything and retrieve by similarity. The result: bloated context, irrelevant chunks, no structure, no forgetting. Your AI drowns in its own memories.

### Birkin's Approach: Compile, Don't Dump

```
Day 1: "I'm a marketer at Iris Corp working on project Chumori"
        → wiki page: entities/user-profile (confidence: 0.8)

Day 5: User asks about Chumori again
        → user-profile.confidence += 0.1, reference_count += 1

Day 30: Old session about weather
        → decayed below threshold, naturally forgotten
```

Every conversation passes through an **LLM classifier** that decides what's worth keeping, categorizes it, and writes structured wiki pages with `[[wikilinks]]` connecting related knowledge.

### How It Works

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│ Conversation │ ──→ │ LLM          │ ──→ │ Wiki Pages      │
│              │     │ Classifier   │     │ - entities/     │
│              │     │ (KO/EN)      │     │ - concepts/     │
│              │     │              │     │ - sessions/     │
└─────────────┘     └──────────────┘     │ - workflows/    │
                                          └────────┬────────┘
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

| Feature | What It Does |
|---|---|
| **Compile, don't dump** | Conversations distilled into structured wiki pages, not thrown into a vector DB |
| **Natural decay** | 20-day half-life — frequently referenced knowledge strengthens, noise fades |
| **Wikilink graph** | Pages connect via `[[links]]` — your knowledge forms a navigable network |
| **Profile import** | Drop your ChatGPT/Claude export JSON → Birkin builds 35+ linked profile pages instantly |
| **Memory ↔ Workflow bridge** | LLM workflow nodes auto-receive memory context; results write back to wiki |
| **Audit trail** | Every page shows what it knows, why, where it came from, how many times accessed |
| **Daily compilation** | 3 AM cron distills sessions into permanent knowledge + cleans old sessions |
| **Bilingual** | Korean + English entity extraction, classification, and semantic search |

### What This Looks Like

Import 26 Claude conversations → Birkin creates **35 interconnected wiki pages**:

```
entities/user-profile  ──→ [[skill-퍼포먼스마케팅]] [[project-birkin]] [[tool-claude-code]]
concepts/project-birkin ──→ [[tool-python]] [[tool-github]] [[skill-ai에이전트]]
concepts/skill-퍼포먼스마케팅 ──→ [[tool-meta-ads]] [[project-추모리]]
entities/person-조상민 ──→ [[project-vws]]
```

Each page is a node in the Memory tab's force-directed graph. Click any node to read, edit, or delete.

---

## Workflows

### The Problem

You do the same 5-step process every Monday. Summarize → draft → review → send → log. Your AI can do each step — but can't chain them, trigger them on schedule, or recover when step 3 fails.

### Birkin's Approach: Visual Graph Engine

Describe what you want. Birkin builds it.

```
"매일 아침 HN 탑 뉴스 요약해서 텔레그램으로 보내줘"

→ Cron trigger (0 9 * * *)
  → HN Fetch node
    → Summarizer node
      → Telegram Send node
```

<p align="center">
  <img src="docs/screenshots/02-workflow.png" width="720" alt="Workflow Editor" />
</p>

### 47 Node Types

| Category | Nodes |
|---|---|
| **AI** | LLM, classifier, embedder, summarizer, translator, knowledge-extract |
| **Tools** | Web search, code execution, API calls, file read/write |
| **Control** | Conditions (YES/NO routing), loops, delays, parallel fan-out, merge |
| **Quality** | Code review gate, human review, guardrails, validators, test runners |
| **I/O** | Input, output, prompt template, webhook trigger |
| **Platform** | Telegram send, email send, HackerNews fetch, notifications |

### 4 Trigger Types

| Type | Example |
|---|---|
| **Cron** | `0 9 * * 1-5` — every weekday at 9 AM |
| **File Watch** | `*.md` changed in `~/notes/` → run analysis |
| **Webhook** | POST to `/api/triggers/webhooks/{id}` → execute workflow |
| **Message** | "urgent" in Telegram message → notify + escalate |

### Workflow Intelligence

Birkin doesn't just run workflows — it **suggests** them:

1. **Pattern detection** — Detects repeated tool calls (e.g., `web_search` used 5x this week)
2. **Proactive suggestion** — "You search for news daily. Want me to automate this?"
3. **Feedback loop** — Accept, dismiss, or modify suggestions. Birkin learns from your choices
4. **Memory bridge** — Workflow results automatically write back to wiki as knowledge pages

---

## Quick Start

```bash
# One-liner
git clone https://github.com/ashmoonori-afk/birkin.git && cd birkin
scripts/start.sh          # → http://127.0.0.1:8321

# Or Docker
cp .env.example .env && docker compose up -d

# Or manual
python3 -m venv .venv && source .venv/bin/activate
pip install -e "." && birkin
```

### API Keys

Add to `.env` — only the ones you use:

```bash
ANTHROPIC_API_KEY=sk-ant-...    # Claude
OPENAI_API_KEY=sk-...           # GPT + OpenRouter
GEMINI_API_KEY=...              # Gemini
GROQ_API_KEY=gsk_...            # Fast inference
```

**No API key?** Birkin auto-detects local Claude CLI and Ollama. Zero cost, zero setup.

### 9 Providers, Auto-Routing

Set `provider: "auto"` and Birkin picks the cheapest model that fits the task.

| Provider | Strength | Local? |
|---|---|---|
| Claude | Reasoning, code | |
| GPT-4 | General, tools | |
| Gemini | Multimodal, 1M context | |
| Perplexity | Web search | |
| Groq | Ultra-fast | |
| Ollama | Private, free | Yes |
| OpenRouter | 100+ models | |
| Claude CLI | Claude Code local | Yes |
| Codex CLI | Codex local | Yes |

---

## Security

Birkin runs on your machine. We take that seriously.

| Layer | How |
|---|---|
| **Memory** | 9 regex patterns neutralize prompt injection before wiki save |
| **Skills** | AST static analysis blocks `subprocess`, `eval`, `exec`, `socket` before install |
| **Shell** | Command allowlist — only safe read-only commands; metacharacters rejected |
| **Actions** | External actions require explicit user approval via ApprovalGate |
| **Audit** | Every memory write/read logged with source, confidence, and reason |
| **Self-check** | `GET /api/security/check` — 8-point diagnostic with score + grade |

---

## Architecture

```
birkin/
├── core/           Agent loop, 9 providers, graph engine, recommender
├── memory/         Wiki (5 categories), compiler, classifier, semantic search, audit
├── gateway/        FastAPI (18 routers, 66 endpoints)
├── triggers/       Cron, file watch, webhook, message
├── skills/         10 built-in skills + AST sandboxing
├── tools/          Shell, file ops, web search, wiki read
├── mcp/            MCP client + server + browser automation
├── eval/           Evaluation framework + recommender quality harness
├── web/            10-tab WebUI (iMessage-grade chat)
└── tests/          724+ tests
```

### Design Principles

1. **Compile over retrieve** — Don't search raw conversations; distill them into structured knowledge
2. **Local-first** — SQLite WAL, no network database, data never leaves your machine
3. **Transparent** — Every memory page shows its source, confidence, and access history
4. **Minimal surface** — No marketplace, no WebSocket, allowlisted commands, AST-validated skills

---

## Compared To

| | Open WebUI | LobeChat | **Birkin** |
|---|---|---|---|
| Memory | Vector RAG | None | **Compiled wiki + decay + wikilinks** |
| Workflows | Pipelines | None | **47-node graph + 4 trigger types** |
| Learns you | No | No | **Pattern detection → proactive suggestions** |
| Korean NER | No | No | **Native bilingual** |
| Security | 138 CVEs (Q1 2026) | Limited | **8-point self-check, AST sandbox** |
| Tests | ~200 | ~100 | **724+** |

---

## Contributing

```bash
pip install -e ".[dev]"
pytest                    # Run tests
ruff check . && ruff format --check .  # Lint
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## License

MIT — see [LICENSE](LICENSE).

Built by humans who got tired of re-introducing themselves to their AI.
