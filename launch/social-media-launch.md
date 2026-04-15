# Social Media Launch Content

**Status:** Ready for review. Adapt timing and links before publishing.

---

## X/Twitter Launch Thread

### Tweet 1 — Hook
We built an AI agent for people who don't know what an AI agent is.

Introducing Birkin — open-source, messaging-first, self-improving.

Talk to your AI from Telegram. No terminal required.

### Tweet 2 — Demo
Here's what it looks like: you send a message on Telegram, and your agent handles the rest.

Web search. File management. Scheduling. Code execution. 40+ tools, plain language.

[Attach: Telegram conversation GIF/screenshot]

### Tweet 3 — Differentiators
What makes Birkin different:

- Messaging-first — Telegram, Discord, Slack, WhatsApp
- Self-improving — learns from every interaction
- 200+ model providers, zero vendor lock-in
- MIT-licensed core — fork it, own it
- Runs on a $5 VPS or scales to a GPU cluster

### Tweet 4 — Open Source
Everything in the core is MIT-licensed and free:

- Full agent runtime
- All 40+ tools
- Messaging gateway
- CLI + setup wizard
- Skill system + MCP integration

Premium adds cybersecurity management, team workspaces, and managed hosting.

### Tweet 5 — Origin
Built in Korea, designed for the world.

We care about the people AI forgot: non-technical workers, small business owners, freelancers who need an assistant but don't have a developer on staff.

### Tweet 6 — CTA
Try it now:

```
git clone https://github.com/MoonGwanghoon/birkin.git
cd birkin && uv pip install -e ".[all]"
birkin setup
```

Star the repo. Join our Discord. Build something.

[Link: GitHub repo]
[Link: Discord invite]

### Tweet 7 — Getting Started
Full getting started guide: [link to docs]

5 minutes to your first conversation.
30 minutes to your first custom tool.
1 hour to a working Telegram bot.

---

## Hacker News — Show HN

**Title:** Show HN: Birkin – Open-source AI agents for everyone, not just engineers

**Body:**

Hi HN,

We're building Birkin, an open-source AI agent platform focused on accessibility.

The problem: every AI agent framework assumes Python, Docker, and prompt engineering knowledge. The people who would benefit most from AI agents — office workers, small business owners, freelancers — can't use any of them.

Birkin is messaging-first. Install it, connect it to Telegram or Discord, and talk to it in plain language. It handles web search, file management, scheduling, and 40+ other capabilities. It learns from your interactions and gets better over time.

Technical details for HN readers:
- MIT-licensed core, open-core business model
- 200+ model providers (OpenRouter, Ollama, direct APIs) — no vendor lock-in
- Built-in skill system — community-contributed capabilities
- MCP integration for tool extensibility
- Session persistence with SQLite + FTS5
- Context compression for long conversations
- Runs on anything from a $5 VPS to a GPU cluster
- Serverless deployment on Modal and Daytona

The premium tier adds cybersecurity management (vulnerability scanning, threat detection) and team features. The core is and will remain fully open source.

Stack: Python 3.11+, OpenAI-compatible API abstraction, Node.js for WhatsApp bridge.

GitHub: https://github.com/MoonGwanghoon/birkin
Getting started takes about 5 minutes.

We'd love feedback on the architecture, the messaging-first approach, and whether the accessibility angle resonates.

---

## Reddit Posts

### r/LocalLLaMA

**Title:** Birkin: open-source AI agent platform with Telegram/Discord/Slack integration, 200+ model providers including Ollama

Hey r/LocalLLaMA,

Sharing Birkin — an open-source AI agent that works through messaging apps. Built to be accessible to non-technical users while keeping full power for developers.

Why it matters for this community:
- Works with Ollama and any local model out of the box
- 200+ provider support via OpenRouter, plus direct API connections
- No vendor lock-in — switch models with one config change
- Built-in RL training pipeline for model fine-tuning
- Self-hosted, your data stays local

MIT-licensed core. GitHub: https://github.com/MoonGwanghoon/birkin

### r/selfhosted

**Title:** Birkin — self-hosted AI agent with Telegram bot, runs on a $5 VPS

For anyone wanting a personal AI assistant without cloud dependencies:

- One-command install, guided setup
- Connect to Telegram, Discord, Slack, or WhatsApp
- 40+ built-in tools (web search, file ops, scheduling, browser automation)
- Session persistence — your agent remembers context
- Runs on a cheap VPS, laptop, or Docker container
- Scales to zero with Modal/Daytona for near-zero idle cost

MIT-licensed, Python 3.11+, no mandatory cloud services.

GitHub: https://github.com/MoonGwanghoon/birkin

### r/artificial

**Title:** We're building AI agents for people who don't know what AI agents are

Most AI agent platforms target developers. We built Birkin for everyone else.

The idea: install it once, connect it to Telegram or WhatsApp, and talk to it in plain language. No code. No configuration files. No prompt engineering.

Your agent learns from your interactions, builds skills over time, and handles real work — not just chat.

Open-source (MIT), messaging-first, 200+ model providers.

GitHub: https://github.com/MoonGwanghoon/birkin

---

## Content Calendar (First 30 Days)

| Day | Platform | Content |
|-----|----------|---------|
| 0 | GitHub | Release v0.1.0, enable Discussions |
| 0 | X/Twitter | Launch thread (above) |
| 0 | Discord | Server goes live, welcome + getting started pinned |
| 0 | HN | Show HN post |
| 0 | Reddit | Posts in r/LocalLLaMA, r/selfhosted, r/artificial |
| 3 | X/Twitter | "Day 3: X new stars, first community question answered" |
| 7 | X/Twitter | First weekly "What's New" update |
| 7 | Discord | Pin first community showcase |
| 14 | X/Twitter + blog | Tutorial: "Deploy Birkin on a $5 VPS" |
| 21 | X/Twitter + blog | Tutorial: "Connect Birkin to Telegram in 5 minutes" |
| 28 | X/Twitter | Month 1 retrospective, community stats |

---

*All content should pass the test: "Would a non-technical person understand this?"*
