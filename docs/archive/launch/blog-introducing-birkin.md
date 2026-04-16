# Introducing Birkin: AI Agents for Everyone

*Reference: [BRA-49 Plan Section 6](/BRA/issues/BRA-49#document-plan) — Launch Day blog post*

---

**Status:** Draft — ready for review after product screenshots are available.

---

Every few months, a new AI agent framework gets developers excited. AutoGPT. CrewAI. LangChain Agents. They're impressive engineering — and completely inaccessible to the people who would benefit most.

My mom runs a small business. She spends hours each week on tasks that an AI agent could handle in minutes: sorting emails, scheduling follow-ups, pulling inventory reports, drafting responses to vendors. But every agent tool on the market assumes you know Python, can configure Docker, and understand what "prompt engineering" means.

**That's the problem Birkin was built to solve.**

## What Is Birkin?

Birkin is an open-source AI agent platform designed for people who want AI to handle real work — without writing a single line of code.

Install it in 30 seconds. Connect it to Telegram, Discord, Slack, or WhatsApp. Talk to it like you'd talk to a capable assistant. It handles the rest.

```bash
git clone https://github.com/MoonGwanghoon/birkin.git
cd birkin && uv pip install -e ".[all]"
birkin setup
birkin chat
```

That's it. You're running a self-improving AI agent.

## What Makes Birkin Different

### 1. Self-Improving Agents

Most AI tools start from zero every conversation. Birkin remembers.

Every time you interact with your agent, it builds skills and memory that make it better over time. Ask it to summarize your emails in a specific format once, and it learns the pattern. Next time, it does it without being told.

No manual training. No configuration files. It just gets better.

### 2. Messaging-First Design

Not everyone lives in a terminal. Birkin works from the apps you already use:

- **Telegram** — Talk to your agent from your phone
- **Discord** — Run agents in your team server
- **Slack** — Integrate with your work workspace
- **WhatsApp** — The messaging app 2 billion people already use
- **Signal** — For the privacy-conscious

Your agent is wherever you are.

### 3. 200+ Model Providers, Zero Lock-In

Use OpenAI, Anthropic, Mistral, open-source models on Ollama, or any of 200+ providers. Switch with one command. Your agent, your choice.

```bash
birkin config --provider anthropic
# or
birkin config --provider ollama --model llama3
```

No vendor lock-in. No surprise bills from a single provider.

### 4. Runs Anywhere, Costs Almost Nothing

Birkin runs on:
- Your laptop (free, for development)
- A $5/month VPS (always-on personal agent)
- Modal or Daytona (serverless — scales to zero, costs near-zero when idle)
- A GPU cluster (for local model inference and RL training)

Your data stays on your infrastructure. Always.

### 5. Enterprise-Grade Security (Premium)

For teams that need more, Birkin's premium tier adds:
- Automated vulnerability scanning
- Threat detection dashboards
- Security policy enforcement
- Team workspaces with role-based access control
- Analytics and audit logs

## Built from the Ground Up

Birkin is a ground-up AI agent platform with 40+ tools, MCP integration, and a built-in skill system. Inspired by the open-source AI agent community — and designed with a singular focus on accessibility.

The engineering depth is there for developers who want it. But you don't need to see it to benefit from it.

## Who Is Birkin For?

**For everyone who isn't a developer:**
- Small business owners automating repetitive tasks
- Office workers managing email, scheduling, and reporting
- Freelancers who need an always-on assistant
- Teams that want shared AI agents without shared technical debt

**For developers who want more:**
- 200+ model providers with a clean abstraction layer
- Full plugin system with community skill marketplace
- Built-in reinforcement learning pipeline
- MIT-licensed core — fork it, extend it, own it

## Get Started

```bash
git clone https://github.com/MoonGwanghoon/birkin.git
cd birkin && uv pip install -e ".[all]"
birkin setup
```

<!-- TODO: Add screenshot of first conversation here -->
<!-- TODO: Add GIF of Telegram interaction here -->

**Links:**
- GitHub: [MoonGwanghoon/birkin](https://github.com/MoonGwanghoon/birkin)
- Documentation: [getbirkin.com](https://getbirkin.com)
- Discord: <!-- TODO: Add invite link -->

---

*Birkin is MIT-licensed at its core. Start free. Upgrade when your AI needs grow.*
