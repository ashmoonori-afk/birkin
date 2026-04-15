<p align="center">
  <strong>Birkin</strong><br>
  <em>AI that works for you, not the other way around.</em>
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> &bull;
  <a href="#features">Features</a> &bull;
  <a href="docs/">Documentation</a> &bull;
  <a href="ROADMAP.md">Roadmap</a> &bull;
  <a href="CONTRIBUTING.md">Contributing</a> &bull;
  <a href="#community">Community</a>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT License"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/models-200%2B-green" alt="200+ Models">
</p>

---

**Birkin** is an AI agent platform that makes powerful AI accessible to everyone — not just engineers. Deploy agents that learn, remember, and act on your behalf through a simple conversational interface.

> Inspired by [Hermes Agent](https://github.com/NousResearch/Hermes-Agent) by Nous Research. Birkin is an independent project.

---

## Features

| For Everyone | For Developers |
|--------------|---------------|
| Plain-language commands — no code required | 200+ model providers, zero vendor lock-in |
| Works from Telegram, Discord, Slack, WhatsApp | MIT-licensed core — fork, extend, own it |
| Agents that learn and improve over time | 40+ built-in tools, MCP integration, subagent delegation |
| Schedule tasks, automate workflows, manage reports | Built-in RL training pipeline, research-ready |
| Enterprise-grade security out of the box | Runs on a $5 VPS or a GPU cluster |

### What Makes Birkin Different

- **Self-improving agents** — Built-in learning loop creates skills from experience. Your agent gets better the more you use it.
- **Messaging-first** — Talk to your agent from Telegram, WhatsApp, Discord, or Slack. Not just a terminal.
- **Cybersecurity management** — Premium tier addresses enterprise vulnerability scanning, threat detection, and security policy enforcement.
- **Serverless-ready** — Deploy on Modal or Daytona for near-zero cost when idle. Scale up when you need it.

---

## Quick Start

```bash
# Clone the repository
git clone https://github.com/MoonGwanghoon/birkin.git
cd birkin

# Install with uv (recommended) or pip
uv pip install -e ".[all]"
# or: pip install -e ".[all]"

# Run the setup wizard
birkin setup

# Start chatting
birkin chat
```

**Requirements:** Python 3.11+ &bull; Node.js 18+ (for browser tools)

---

## How It Works

```
You (plain language)  →  Birkin Agent  →  Action
     ↑                       ↓
     └── Response ← Skills + Tools + Memory
```

1. **Tell Birkin what you need** in plain language — from your terminal or messaging app.
2. **Birkin plans and acts** using 40+ tools: web search, file operations, code execution, browser automation, and more.
3. **Birkin learns** from every interaction, building skills and memory that make it better over time.

---

## Comparison

| Feature | **Birkin** | AutoGPT | CrewAI | LangChain Agents |
|---------|-----------|---------|--------|-----------------:|
| Target user | Everyone | Developers | Developers | Developers |
| Setup difficulty | One command | High | Medium | High |
| Learning loop | Built-in | Limited | None | None |
| Messaging platforms | Telegram, Discord, Slack, WhatsApp | None | None | None |
| Model providers | 200+ | OpenAI-centric | Multiple | Multiple |
| Serverless deploy | Modal, Daytona | No | No | No |
| Cybersecurity focus | Premium tier | No | No | No |

---

## Architecture

```
birkin/
├── agent/          # Core agent loop, context management, memory
├── tools/          # 40+ built-in tools (terminal, web, files, browser, etc.)
├── skills/         # Bundled skill library
├── gateway/        # Multi-platform messaging (Telegram, Discord, Slack, WhatsApp)
├── birkin_cli/     # CLI interface and setup wizard
├── web/            # Web UI components
└── tests/          # Test suite
```

---

## Messaging Platforms

Connect Birkin to your preferred messaging platform:

| Platform | Status | Setup Guide |
|----------|--------|-------------|
| **Telegram** | Stable | `birkin gateway --platform telegram` |
| **Discord** | Stable | `birkin gateway --platform discord` |
| **Slack** | Stable | `birkin gateway --platform slack` |
| **WhatsApp** | Stable | `birkin gateway --platform whatsapp` |
| **Signal** | Beta | `birkin gateway --platform signal` |
| **CLI** | Stable | `birkin chat` |

---

## Self-Hosting

Birkin runs anywhere Python runs:

| Environment | Cost | Best For |
|------------|------|----------|
| Local machine | Free | Development, testing |
| $5/mo VPS | ~$5/mo | Personal agent, always-on |
| Modal | Pay-per-use | Serverless, scales to zero |
| Daytona | Pay-per-use | Cloud dev environments |
| GPU cluster | Varies | Local model inference, RL training |

---

## Premium Features

Start free with the full open-source core. Upgrade when you need:

| Feature | Free (OSS) | Premium |
|---------|:----------:|:-------:|
| All 200+ model providers | Yes | Yes |
| CLI + messaging platforms | Yes | Yes |
| Learning loop, skills, memory | Yes | Yes |
| Community support | Yes | Yes |
| Cybersecurity management harness | — | Yes |
| Team workspace with RBAC | — | Yes |
| Analytics dashboard | — | Yes |
| Managed hosting with SLA | — | Yes |
| Priority support (24h SLA) | — | Yes |

---

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide.

**Quick version:**

1. Fork the repo and create a feature branch
2. Make your changes (skills are usually better than tools — see the guide)
3. Run tests: `pytest tests/ -q`
4. Submit a PR with clear description

**Good first issues** are labeled [`good-first-issue`](https://github.com/MoonGwanghoon/birkin/labels/good-first-issue).

---

## Community

- **Discord** — Questions, showcasing projects, sharing skills <!-- TODO: Add Discord invite link -->
- **GitHub Issues** — Bug reports and feature requests
- **GitHub Discussions** — Ideas, Q&A, community showcase

---

## License

MIT — see [LICENSE](LICENSE) for details.

Copyright (c) 2026 Birkin Team. Inspired by Hermes Agent (MIT, Nous Research).
