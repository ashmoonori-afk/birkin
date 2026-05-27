<div align="center">

```
 ██████╗ ██╗██████╗ ██╗  ██╗██╗███╗   ██╗
 ██╔══██╗██║██╔══██╗██║ ██╔╝██║████╗  ██║
 ██████╔╝██║██████╔╝█████╔╝ ██║██╔██╗ ██║
 ██╔══██╗██║██╔══██╗██╔═██╗ ██║██║╚██╗██║
 ██████╔╝██║██║  ██║██║  ██╗██║██║ ╚████║
 ╚═════╝ ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝
```

### The AI agent that actually remembers you.

A lightweight, **self-improving** CLI agent workspace — with skill management,
subagents, an Obsidian-vault memory, and a nightly routine that makes your
tomorrow easier.

![python](https://img.shields.io/badge/python-3.10%2B-3776ab)
![runtime deps](https://img.shields.io/badge/runtime%20deps-0-2ea44f)
![platform](https://img.shields.io/badge/platform-macOS%20·%20Linux%20·%20Windows-lightgrey)
![license](https://img.shields.io/badge/license-MIT-green)

</div>

---

Most AI tools forget you the moment a chat ends. **birkin doesn't.** It
*compiles* what it learns into an Obsidian knowledge vault, builds its own
skills from experience, and every night at 04:00 it reviews your day to prepare
the next one — asking your permission before it changes anything that matters.

Inspired by [hermes-agent](https://github.com/NousResearch/hermes-agent) and
[openclaw](https://github.com/openclaw/openclaw), distilled to a **zero-dependency**
core you can read in an afternoon.

## ✨ Highlights

- 🧠 **Memory that lasts** — an **Obsidian vault** of linked markdown notes
  (`[[wikilinks]]`, frontmatter, sources). *Compile over retrieve* — no opaque
  vector store.
- 🌙 **Self-improving, nightly** — at 04:00 it studies the last 24h of
  conversation and changed files, then updates memory, authors skills, and
  **proposes** automations for your approval.
- 🧩 **Skills** — the `SKILL.md` standard (hermes-compatible). The agent loads
  skills on demand and writes new ones from what it learns.
- 🐝 **Subagents** — delegate focused work to isolated agents in parallel.
- ✅ **You stay in control** — consequential actions (cron jobs, commands) wait
  in an approval queue. Tune the boundary with `/permission`.
- 📊 **Dashboard, not chatbox** — a local web dashboard shows running jobs, run
  summaries, and pending approvals. Chat stays in your terminal.
- 🪶 **Zero dependencies** — Python standard library only. One command, any OS.

## 🚀 Install

**macOS / Linux**
```bash
curl -fsSL https://raw.githubusercontent.com/ashmoonori-afk/birkin/main/scripts/install.sh | bash
```

**Windows (PowerShell)**
```powershell
irm https://raw.githubusercontent.com/ashmoonori-afk/birkin/main/scripts/install.ps1 | iex
```

**Or from source**
```bash
git clone https://github.com/ashmoonori-afk/birkin && cd birkin
uv run birkin          # or: pip install -e . && birkin
```

Then set your key:
```bash
export ANTHROPIC_API_KEY=sk-ant-...      # PowerShell: $env:ANTHROPIC_API_KEY="sk-ant-..."
```

## 🎮 Usage

```bash
birkin                 # start chatting
birkin web             # open the monitoring dashboard
birkin daemon          # run the 04:00 self-improvement + cron scheduler
birkin nightly         # run the self-improvement routine right now
birkin review          # approve / reject what birkin proposed
birkin skills          # browse skills   ·   birkin skills <name> to read one
birkin permission      # see / change which actions auto-apply
birkin setup           # configure provider, model, vault, nightly hour
```

In chat, slash commands: `/help` `/skills` `/new` `/model` `/learn`
`/permission` `/save` `/quit`.

## 🧠 How memory works

birkin keeps an **Obsidian vault** (default `~/.birkin/vault`). Open it in
Obsidian and watch the graph grow.

```markdown
---
title: FlowerPlus GTM
type: project
created: 2026-05-27
confidence: 0.8
sources: ["session:2026-05-27"]
tags: [marketing, gtm]
---

Corporate-welfare flower subscription. Relates to
[[User Research]] and [[Outbound Sales Script]].
```

Every note is human-readable, editable, and sourced. Nothing is hidden in an
embedding you can't inspect.

## 🌙 The nightly routine

At your configured hour (default **04:00**), `birkin daemon` wakes and:

1. **Reads your last 24h** — conversations + files that changed.
2. **Updates memory** — new entities, facts, and `[[links]]`. *(auto)*
3. **Writes skills** — for repeatable things it saw. *(auto)*
4. **Proposes** — digests, prefetches, reminders, cron jobs. *(needs your OK)*

Safe, reversible changes (memory, skills) apply automatically; anything that
touches the outside world waits for `birkin review`. Change that boundary
anytime with `/permission add cron` etc.

## 🗺️ Architecture

```
birkin/
├── cli.py            # single entry: chat · web · daemon · nightly · review · …
├── agent.py · llm.py # tool-calling loop + Anthropic/OpenAI client
├── tools/            # files · shell · web · subagent
├── skills/           # SKILL.md loader · manager · self-authoring
├── memory.py         # Obsidian-vault semantic memory
├── subagent.py       # isolated child agents
├── nightly.py        # 04:00 self-improvement routine
├── scheduler.py · cron.py · approvals.py · store.py   # autonomy + approval gate
└── web/              # monitoring dashboard
```

Full design: [`docs/DESIGN.md`](./docs/DESIGN.md) · decisions:
[`docs/DECISIONS.md`](./docs/DECISIONS.md) · status:
[`docs/STATUS.md`](./docs/STATUS.md).

## ⚙️ Configuration

State lives under `~/.birkin` (override with `BIRKIN_HOME`):

```
~/.birkin/
├── config.json   vault/   skills/   sessions/
├── runs/         pending/  cron.json  status.json
```

API keys are read from the environment first (`ANTHROPIC_API_KEY` /
`OPENAI_API_KEY`); they never need to touch disk.

## 📦 Requirements

Python **3.10+**. No third-party runtime packages.

## 📄 License

MIT.
