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

A lightweight, **self-improving** CLI agent workspace: skill management,
subagents, an Obsidian-vault memory, a monitoring dashboard, and a nightly
routine that prepares your tomorrow — all in a **zero-dependency** Python core.

![python](https://img.shields.io/badge/python-3.10%2B-3776ab)
![runtime deps](https://img.shields.io/badge/runtime%20deps-0-2ea44f)
![platform](https://img.shields.io/badge/platform-macOS%20·%20Linux%20·%20Windows-lightgrey)
![license](https://img.shields.io/badge/license-MIT-green)

</div>

---

Most AI tools forget you the moment a chat ends. **birkin doesn't.** It
*compiles* what it learns into an Obsidian knowledge vault, writes its own
skills from experience, and every night reviews your day to prepare the next
one — asking permission before it changes anything that matters.

It runs on whatever you already have: an **API key** (Anthropic / OpenAI-compatible)
**or** a locally-installed agent CLI you're already logged into
(**Claude Code** or **Codex**).

Inspired by [hermes-agent](https://github.com/NousResearch/hermes-agent) and
[openclaw](https://github.com/openclaw/openclaw), distilled to a core you can
read in an afternoon.

## ✨ Highlights

- 🧠 **Memory that lasts** — an **Obsidian vault** of linked markdown notes
  (`[[wikilinks]]`, frontmatter, sources). *Compile over retrieve* — no opaque
  vector store; open it in Obsidian and edit by hand.
- 🔌 **Run on what you have** — Anthropic API, any OpenAI-compatible endpoint
  (incl. local **Ollama**), or your installed **Claude Code** / **Codex** CLI
  (no API key — it uses the CLI's own login).
- 🧩 **Skills** — the `SKILL.md` standard (hermes-compatible). Skills load on
  demand; the agent authors new ones from what it learns.
- 🐝 **Subagents** — delegate focused, parallelizable work to isolated agents.
- 🌙 **Self-improving, nightly** — at 04:00 it reviews the last 24h, updates
  memory, writes skills, and **proposes** automations for your approval.
- ✅ **You stay in control** — consequential actions (cron jobs, shell) wait in
  an approval queue. Tune the boundary with `/permission`.
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

**From source**
```bash
git clone https://github.com/ashmoonori-afk/birkin && cd birkin
uv run birkin            # or:  pip install -e .  &&  birkin
```

Requires **Python 3.10+**. The first run launches an onboarding wizard.

### Pick a backend

birkin needs *one* of these — the onboarding wizard (or `birkin model`) sets it up:

| Backend | How | API key |
|---|---|---|
| **Anthropic** | `export ANTHROPIC_API_KEY=sk-ant-…` | required |
| **OpenAI-compatible** | set provider `openai` + `base_url` (works with **Ollama**) | required* |
| **Claude Code** (`claude`) | pick it in `birkin model` | none — uses the CLI login |
| **Codex** (`codex`) | pick it in `birkin model` | none — uses the CLI login |

\* Ollama accepts any key. PowerShell: `$env:ANTHROPIC_API_KEY="sk-ant-…"`.

### Run on Claude Code / Codex (no API key)

If `claude` or `codex` is on your `PATH`, `birkin model` lists them under
**Local CLI agents**. Selecting one routes birkin through that CLI using its own
login. In this mode birkin is a **thin proxy** — the CLI runs its own tools, so
birkin's native tool-loop, skills, and memory injection apply to the API
providers, not to CLI-agent chat.

## 🎮 Commands

```bash
birkin            # start chatting (first run → onboarding)
birkin setup      # onboarding wizard            (alias: birkin onboard)
birkin model      # choose the model — API + local CLI agents in one picker
birkin tools      # list / --enable / --disable the agent's tools
birkin skills     # list skills   ·   birkin skills <name> to print one
birkin gateway    # run as a service (HTTP + optional Telegram channels)
birkin web        # open the monitoring dashboard
birkin daemon     # run the nightly + cron scheduler  (--install for an OS task)
birkin nightly    # run the self-improvement routine now  (--dry-run to preview)
birkin review     # approve / reject proposed actions
birkin cron       # list / --remove scheduled jobs
birkin permission # view / --add / --remove auto-approved action categories
```

### In-chat slash commands

Self-documenting — type `/help` for the list, `/help <name>` for detail:

| Group | Commands |
|---|---|
| **Conversation** | `/new` · `/retry` · `/undo` · `/compact` · `/clear` |
| **Model** | `/model` · `/models` · `/provider` · `/temp` |
| **Skills** | `/skills` · `/skill <name>` · `/reload` · `/learn` |
| **Memory** | `/memory <query>` · `/remember <text>` · `/vault` |
| **Autonomy** | `/nightly` · `/review` · `/cron` · `/permission` |
| **Session** | `/save` · `/load` · `/sessions` |
| **System** | `/tools` · `/system` · `/config` · `/update` · `/help` · `/quit` |

## 🧠 Memory (Obsidian vault)

birkin keeps an **Obsidian vault** (default `~/.birkin/vault`). Each fact is a
markdown note with frontmatter and `[[wikilinks]]`:

```markdown
---
title: FlowerPlus GTM
type: project            # person | project | preference | fact | topic | session
created: 2026-05-27
updated: 2026-05-27
confidence: 0.8
sources: ["session:2026-05-27"]
tags: [marketing, gtm]
---

Corporate-welfare flower subscription. Relates to
[[User Research]] and [[Outbound Sales Script]].
```

The agent uses `memory_search` to find notes, `memory_get_note` to read them,
and `memory_write_note` / `memory_link` to grow the graph. Everything is
human-readable and sourced — nothing hidden in an embedding.

## 🌙 Nightly self-improvement & the approval gate

Run `birkin daemon` (or register an OS task with `birkin daemon --install`). At
your configured hour (default **04:00**) it:

1. **Reads your last 24h** — saved conversations + files that changed.
2. **Updates memory** — new entities, facts, and `[[links]]`.  *(auto)*
3. **Writes / refines skills** — for repeatable things it saw.  *(auto)*
4. **Proposes** automations (cron jobs, digests, commands).  *(needs approval)*

Safe, reversible changes (memory, skills) apply automatically. Anything that
touches the outside world is queued — review it with `birkin review` or on the
dashboard. The unattended routine runs **without** shell/subagent tools by
design. Adjust what auto-applies with `birkin permission --add cron` (or
`/permission`); `memory` and `skills` are auto-approved by default.

## 🛰️ Gateway

`birkin gateway` runs the agent as a persistent service. One shared memory vault
and skill catalog back every **channel**, so birkin remembers you everywhere:

- **HTTP** (on by default): `POST /message {"session","text"} → {"reply"}` and
  `GET /health`, bound to localhost.
- **Telegram** (optional): run `birkin setup` and answer *“Connect a Telegram
  bot?”* (it verifies the token via `getMe`), or set `channels.telegram =
  {"enabled": true, "token": "<bot token>"}` in `~/.birkin/config.json`. Create
  the bot with [@BotFather](https://t.me/BotFather). Pure stdlib long-polling —
  start it with `birkin gateway`.

## 📊 Dashboard

`birkin web` serves a local **monitoring dashboard** (not a chat): live status,
scheduled/running jobs, recent run summaries, pending approvals (approve/reject),
and the skill catalog. It is read-mostly, needs no API key, is bound to
localhost, and guards approvals with a per-session token + Host check.

## ⚙️ Configuration

All state lives under `~/.birkin` (override with `BIRKIN_HOME`):

```
~/.birkin/
├── config.json     # provider, model, vault, nightly hour, permissions, channels…
├── vault/          # Obsidian semantic memory (markdown notes)
├── skills/         # user- and agent-authored skills
├── sessions/       # saved conversations  (nightly input)
├── runs/           # nightly / cron run summaries  (dashboard)
├── pending/        # proposed actions awaiting approval
├── cron.json       # registered daily jobs
└── status.json     # daemon heartbeat / next-run info
```

`config.json` (key settings):

```json
{
  "provider": "anthropic",            // anthropic | openai | claude-cli | codex-cli
  "model": "claude-sonnet-4-6",
  "subagent_model": "claude-haiku-4-5-20251001",
  "base_url": "",                     // e.g. http://localhost:11434/v1 for Ollama
  "vault_path": "",                   // empty → ~/.birkin/vault
  "nightly_hour": 4,
  "auto_approve": ["memory", "skills"],
  "disabled_tools": [],
  "gateway_port": 8788,
  "web_port": 8787,
  "channels": { "http": {"enabled": true}, "telegram": {"enabled": false, "token": ""} }
}
```

API keys are read from the environment first (`ANTHROPIC_API_KEY` /
`OPENAI_API_KEY`); CLI-agent providers need none. If a key is written to
`config.json` it is stored `chmod 600`.

## 🧩 Skills

A skill is a directory with a `SKILL.md` (YAML frontmatter + markdown body),
compatible with the agentskills.io / hermes standard:

```markdown
---
name: web-research
description: "Research a topic and synthesize a sourced summary."
version: 1.0.0
metadata:
  birkin:
    tags: [research, web]
---

# Web Research
## When to Use
## When NOT to Use
```

Bundled skills ship in [`skills/`](./skills) (40+ across research, software,
writing, data, devops, marketing, …); your own live in `~/.birkin/skills/` and
shadow bundled ones by name. The agent loads a skill on demand with
`load_skill`, and writes/refines its own with `create_skill` / `improve_skill`.

**Automatic skill-ization (hermes-style).** After a complex turn (several tool
steps) that didn't save a skill, birkin nudges itself — with no extra LLM call —
to capture the procedure as a skill; a turn-based nudge does the same for
memory. Counters reset when you actually save. Tune with `skill_nudge_interval`
/ `memory_nudge_interval` in config (set to `0` to disable).

## 🗺️ Architecture

```
birkin/
├── cli.py            # entry: chat·setup·model·tools·gateway·web·daemon·nightly·review·cron·permission
├── onboarding.py     # first-run wizard
├── runtime.py        # wires a Session (client + skills + memory + tools)
├── agent.py          # provider-agnostic tool-calling loop
├── llm.py            # clients: Anthropic (stream) · OpenAI · Claude Code / Codex CLIs
├── models.py         # model discovery (API + local CLI agents + Ollama)
├── prompts.py        # system-prompt construction
├── tools/            # files · shell · web · subagent  (+ registry/context)
├── skills/           # SKILL.md frontmatter parser · loader · manager
├── memory.py         # Obsidian-vault semantic memory
├── subagent.py       # isolated child agents
├── selfimprove.py    # reflection → skills/memory
├── nightly.py        # 04:00 routine
├── scheduler.py · cron.py · approvals.py · store.py   # autonomy + approval gate
├── gateway/          # service control plane + channels (HTTP, Telegram)
├── repl.py · ui.py · slashcommands.py                 # terminal chat
└── web/              # monitoring dashboard (server + static UI)
```

Full design: [`docs/DESIGN.md`](./docs/DESIGN.md) ·
decisions: [`docs/DECISIONS.md`](./docs/DECISIONS.md) ·
status: [`docs/STATUS.md`](./docs/STATUS.md).

## 📄 License

MIT.
