<div align="center">

```
 ██████╗ ██╗██████╗ ██╗  ██╗██╗███╗   ██╗
 ██╔══██╗██║██╔══██╗██║ ██╔╝██║████╗  ██║
 ██████╔╝██║██████╔╝█████╔╝ ██║██╔██╗ ██║
 ██╔══██╗██║██╔══██╗██╔═██╗ ██║██║╚██╗██║
 ██████╔╝██║██║  ██║██║  ██╗██║██║ ╚████║
 ╚═════╝ ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝
```

### Self-improving by night. Audited by you.

A lightweight CLI agent workspace that **improves itself overnight and leaves
you the receipts**: an approval-gated nightly routine (**Morpheus**), per-turn
run records + an append-only audit ledger, a polarity-aware Obsidian memory,
risk-tiered approvals, and a `skills validate` integrity gate — all in a
**zero-dependency** Python core.

![python](https://img.shields.io/badge/python-3.10%2B-3776ab)
![runtime deps](https://img.shields.io/badge/runtime%20deps-0-2ea44f)
![tests](https://img.shields.io/badge/tests-265%20passing-2ea44f)
![coverage](https://img.shields.io/badge/coverage-76%25-2ea44f)
![platform](https://img.shields.io/badge/platform-macOS%20·%20Linux%20·%20Windows-lightgrey)
![license](https://img.shields.io/badge/package-Proprietary-orange)
![license](https://img.shields.io/badge/bundled%20skills-MIT-green)

</div>

---

Most self-improving agents either lock you out of their decisions or leave no
trail. **birkin does neither.** While you sleep, **Morpheus** reads your day,
updates an Obsidian memory vault, drafts new skills, and **queues any
consequential action** (cron jobs, shell commands) for your morning review.
Every turn writes a run record plus a one-line ledger entry, so you can
replay any past decision — `birkin trace <run-id>`. Memory notes carry a
polarity (positive vs. known failure), a version (optimistic lock), and
optional evidence requirements; bundled skills are linted and `py_compile`d
on demand.

It runs on whatever you already have: an **API key**
(Anthropic / OpenAI-compatible / Ollama) **or** the local agent CLI you're
already logged into (**Claude Code** / **Codex**).

Inspired by [hermes-agent](https://github.com/NousResearch/hermes-agent) and
[openclaw](https://github.com/openclaw/openclaw); positioned deliberately
*not* on breadth (channels, providers, skill count) but on **the depth of
the trust story** — see [`docs/COMPARISON.md`](./docs/COMPARISON.md) for the
sourced breakdown.

---

## 🎯 Design intent

birkin is deliberately **smaller and more careful** than the inspirations. Five
choices everything else falls out of:

1. **Stdlib-only runtime.** `pyproject.toml` `dependencies = []`. Install on
   any laptop, server, or fresh OS — no version drift, no pinning hell. (Dev
   tooling like `pytest` is opt-in.)
2. **Compile over retrieve.** Memory is a real Obsidian vault of markdown
   notes with `[[wikilinks]]`, frontmatter, **polarity** (positive vs. known
   failure), **version** (optimistic lock), and TTL — not an opaque embedding
   store. Open it in Obsidian and edit by hand.
3. **Approval-first.** Memory and skill writes auto-apply (reversible local
   files); cron schedules and shell commands are queued for review. Risk tiers
   surface the most dangerous proposals first.
4. **CLI first, dashboard second.** The chat lives in your terminal with a
   real line editor (inline `/cmd` dropdown, Shift/Ctrl/Alt+Enter newlines,
   persistent history). The web UI is *monitoring* — jobs, runs, approvals.
5. **Honest about scope.** hermes ships more execution backends; openclaw
   ships more channels and a 5,400-skill registry. birkin's bet is **depth on
   trust**: `skills validate` + `py_compile`, risk-tiered approvals, polarity
   memory, token-budget governor, ledgered audit trail. See
   [`docs/COMPARISON.md`](./docs/COMPARISON.md) for the sourced breakdown.

---

## 🗺️ Architecture

```
                              ┌───────────────────────────┐
                              │            you            │
                              └──┬──────────────────────┬─┘
                                 │ terminal             │ browser
                                 ▼                      ▼
              ┌──────────────────────────────┐   ┌────────────────────┐
              │      REPL  (repl.py)         │   │  web/server.py     │
              │  ┌────────────────────────┐  │   │  monitoring only   │
              │  │ inline_complete.py     │  │   │  ─ /api/status     │
              │  │  ─ /cmd dropdown       │  │   │  ─ /api/runs       │
              │  │  ─ Shift/Ctrl/Alt+Ent  │  │   │  ─ /api/approvals  │
              │  │  ─ multi-line + paste  │  │   │  ─ /api/skills     │
              │  │  ─ ↑/↓ history         │  │   └─────────┬──────────┘
              │  └────────────────────────┘  │             │
              └──────────────┬───────────────┘             │
                             │                             │
              ┌──────────────┴─────────────────────────────┴──┐
              │       gateway / channels (gateway/*)          │ ◀── Telegram
              │           one shared Session                  │
              └──────────────┬───────────────────────────────┘
                             │
                             ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │                       Session   (runtime.py)                     │
  │                                                                  │
  │     ┌────────────────────────────────────────────────────┐       │
  │     │        agent.py   ⟲ tool-calling loop              │       │
  │     │        (provider-agnostic, streaming on Anthropic) │       │
  │     └──┬─────────────────────┬─────────────────────────┬─┘       │
  │        ▼                     ▼                         ▼         │
  │   ┌─────────┐         ┌──────────────┐         ┌─────────────┐   │
  │   │  llm.py │         │   tools/     │         │  skills/    │   │
  │   │         │         │              │         │             │   │
  │   │ Anthropic│        │ files        │         │ SKILL.md    │   │
  │   │ OpenAI   │        │ shell        │         │ loader      │   │
  │   │ claude-cli        │ web          │         │ manager     │   │
  │   │ codex-cli│        │ subagent ──┐ │         │ validate.py │   │
  │   │ local-cli│        │ memory_*  ─┼─┼────────▶│  py_compile │   │
  │   └─────────┘         └────────────┼─┘         │  sync       │   │
  │                                    │           └─────┬───────┘   │
  │                                    ▼                 ▼           │
  │                              subagent.py        memory.py        │
  │                              (isolated)         (Obsidian vault) │
  └──────────────────────────────────────────────────────────────────┘
                             │                       │
                             │                       ▼
                             │              ~/.birkin/vault/*.md
                             │              ─ polarity (+/−)
                             │              ─ version (optimistic lock)
                             │              ─ TTL (expires_at)
                             ▼
        ┌────────────────────────────────────────────────────┐
        │   autonomy (scheduler.py · cron.py · morpheus.py)  │
        │                                                    │
        │   04:00 ─▶ selfimprove ─▶ reads last 24h          │
        │            ├─ writes memory / skills    (auto)     │
        │            └─ proposes cron / shell ───┐           │
        └────────────────────────────────────────┼───────────┘
                                                 │
                                                 ▼
                              ┌─────────────────────────────────┐
                              │  approvals.py + risk.py         │
                              │  ─ memory/skill = low (auto)    │
                              │  ─ cron        = medium (queue) │
                              │  ─ shell       = high  (queue)  │
                              └──────────┬──────────────────────┘
                                         │
                                         ▼
                            `birkin review`  /  /api/approvals

        every turn:  run record (estTokens, tools, iterations)
                     ──▶  ~/.birkin/runs/  +  ~/.birkin/ledger.jsonl
                     (audit replay via `birkin trace <run-id>`,
                      budget governor in budget.py)
```

**Reading the diagram.** Solid arrows are control / data flow at one turn.
The dashed regions (autonomy, audit) sit *under* the synchronous loop —
they're driven by the daemon and the ledger, not by user input.

---

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

Requires **Python 3.10+**. The first run launches an onboarding wizard —
navigate with **↑/↓ and Enter** (no typing except keys/paths).

### Pick a backend

birkin needs *one* of these — the wizard (or `birkin model`) sets it up:

| Backend | How | API key |
|---|---|---|
| **Anthropic** | `export ANTHROPIC_API_KEY=sk-ant-…` | required |
| **OpenAI-compatible** | set provider `openai` + `base_url` (works with **Ollama**) | required\* |
| **Claude Code** (`claude`) | pick it in `birkin model` | none — uses CLI login |
| **Codex** (`codex`) | pick it in `birkin model` | none — uses CLI login |
| **Any local CLI** (`local-cli`) | set `cli_command` (argv) in config | none — runs argv with prompt on stdin |

\* Ollama accepts any key. PowerShell: `$env:ANTHROPIC_API_KEY="sk-ant-…"`.

### No API key? Use Claude Code / Codex

If `claude` or `codex` is on your `PATH`, `birkin model` lists them under
**Local CLI agents**. birkin injects its identity + memory + the skills most
relevant to your message into the CLI prompt, so the agent answers *as
birkin*, remembers you, and follows your skills.

CLI agents are **writable** by default (sandboxed to the workspace). To
bypass approvals/sandbox entirely: `birkin permission --access full`.
Use only in a workspace you trust.

---

## 🎮 Quick start — five workflows

> Every example below is real. Copy, paste, run.

### 1. Chat that remembers what you tell it

```bash
$ birkin
you > /remember I prefer concise replies, no preamble
birkin > Noted as [[Profile - reply-style]].
you > /memory preference
birkin > Vault has 3 preference notes:
         - [[Profile - reply-style]] …
         - [[Profile - timezone]] …
```

### 2. Paste a 5000-character PRD as one input

Inside the REPL, **Shift+Enter** (or Ctrl-J / Alt+Enter on terminals
without the Kitty Keyboard Protocol) inserts a newline. **Enter** submits.
Inline `/`-dropdown filters slash commands as you type; arrow keys, Home/End,
Delete, and ↑/↓ history all work. Long lines scroll horizontally so the
terminal layout never breaks.

```
you > /help⏎          (lists every slash command grouped by purpose)
you > Build a GTM plan for the brief below.⇧⏎
      ⇧⏎
      [paste 5000+ chars across N lines]⏎
birkin > [streams reply]
```

### 3. Teach it a skill from one successful turn

```bash
you > /learn lockup-feedback
       → birkin captures the procedure of the last turn as a SKILL.md
         in ~/.birkin/skills/lockup-feedback/. Next time you ask, it
         loads it automatically and follows the same recipe.
```

You can also let birkin **author skills overnight via Morpheus**, gated by
approval (below).

### 4. Morpheus — self-improve overnight, review in the morning

```bash
$ birkin daemon --install      # registers the OS task (cron / launchd / schtasks)
                               # at 04:00 Morpheus reads yesterday, writes memory,
                               # writes skills (auto), and queues automation
                               # proposals for cron / shell (review needed)
$ birkin morpheus --dry-run    # preview what tonight's run would do, no spending
$ birkin review                # next morning, approve / reject one by one
$ birkin trace <run-id>        # audit replay of any past turn
```

Risk tiers surface the dangerous proposals first (`shell` before `cron`
before `memory`/`skill`). See `birkin permission` to tune what auto-applies.

### 5. Reach birkin from Telegram

```bash
$ birkin setup              # answer "Connect a Telegram bot?" — paste token
$ birkin gateway            # now your Telegram bot shares the same vault
                            # and skills as your terminal session
```

---

## 📟 Command cheat sheet

```bash
birkin                              # start chatting (first run → onboarding)
birkin chat --dry-run -m "…"        # print the prompt packet — no model call
birkin runs                         # recent run records + usage (audit log)
birkin trace <run-id>               # single run record (replay-style)
birkin budget                       # token usage vs daily/monthly caps
birkin setup                        # onboarding wizard         (alias: onboard)
birkin model                        # pick model (API + local CLI agents)
birkin tools  [--enable/--disable]  # tool catalog and toggles
birkin skills                       # list   (`<name>` to print, `sync` to mirror upstream)
birkin skills validate [--verbose]  # lint SKILL.md frontmatter + py_compile bundled scripts
birkin gateway                      # run as a service (HTTP + Telegram channels)
birkin web                          # open the monitoring dashboard
birkin daemon  [--install]          # Morpheus + cron scheduler
birkin morpheus [--dry-run]         # run the Morpheus self-improvement routine NOW
                                    # (alias: `birkin nightly` for backwards compatibility)
birkin review                       # approve / reject proposed actions
birkin cron                         # list / --remove scheduled jobs
birkin permission [--add/--remove]  # auto-approve categories
              [--access workspace|full]  # CLI-agent access level
```

### In-chat slash commands

Self-documenting — type `/help` for the full list, `/help <name>` for detail:

| Group | Commands |
|---|---|
| **Conversation** | `/new` · `/retry` · `/undo` · `/compact` · `/clear` |
| **Model** | `/model` · `/models` · `/provider` · `/temp` |
| **Skills** | `/skills` · `/skill <name>` · `/reload` · `/learn` |
| **Memory** | `/memory <query>` · `/remember <text>` · `/vault` |
| **Autonomy** | `/morpheus` (aliased as `/nightly`) · `/review` · `/cron` · `/permission` |
| **Session** | `/save` · `/load` · `/sessions` |
| **System** | `/tools` · `/system` · `/config` · `/update` · `/help` · `/quit` |

---

## 🧠 Memory in detail (Obsidian vault)

Default location: `~/.birkin/vault`. Each fact is a sourced markdown note:

```markdown
---
title: FlowerPlus GTM
type: project              # person | project | preference | fact | topic | session
created: 2026-05-27
updated: 2026-05-28
confidence: 0.8
polarity: positive         # or "negative" — known failure (re-verify on use)
version: 3                 # optimistic-lock: refuse stale-snapshot overwrites
sources: ["session:2026-05-27"]
tags: [marketing, gtm]
---

Corporate-welfare flower subscription. Relates to
[[User Research]] and [[Outbound Sales Script]].
```

Tools the agent uses: `memory_search`, `memory_get_note`, `memory_write_note`
(with `polarity` and `expected_version`), `memory_link`. Set
`evidence_required: true` in `config.json` to refuse any new note that lacks
a `source`.

---

## 🧩 Skills in detail

A skill is a directory with a `SKILL.md` (YAML frontmatter + markdown body),
compatible with the agentskills.io / hermes standard. **48 bundled** under
[`skills/`](./skills) across research, software, writing, data, devops,
marketing, … plus your own under `~/.birkin/skills/` (which shadow bundled
ones by name).

```markdown
---
name: web-research
description: "Research a topic and synthesize a sourced summary."
version: 1.0.0
license: MIT
metadata:
  birkin:
    tags: [research, web]
---

## When to Use
…
```

**Authoring.** `load_skill` pulls the full text on demand. `create_skill`
and `improve_skill` route every write through the approval gate (Skill-PR
mode) — bundled skills are never edited in place; they fork to your user
dir first. After a complex turn that didn't save a skill, birkin nudges
itself (no extra LLM call) to capture the procedure.

**Hygiene.** `birkin skills validate` lints frontmatter and runs
`py_compile` over every bundled `*.py`. Use it in CI: it exits non-zero on
any error.

**Freshness & scale.** Skills **hot-reload** when you edit a `SKILL.md`
(no restart). Add `prerequisites` (commands / platforms) and a skill is
**gated** — hidden when prereqs aren't met. `birkin skills sync` mirrors
an upstream skill tree into `~/.birkin/skills/mirrors/` (bundled scripts +
attribution preserved). If `SOUL.md` / `AGENTS.md` / `TOOLS.md` exist in
your workspace they're layered into the system prompt.

---

## 🌙 Morpheus — nightly self-improvement & the approval gate

The Greek god of dreams. While you sleep, birkin reviews the day.

`birkin daemon` (or `birkin daemon --install` to register an OS task). At
your configured hour (default **04:00**) Morpheus:

1. **Reads your last 24h** — saved conversations + files that changed.
2. **Updates memory** — new entities, facts, and `[[links]]`.   *(auto)*
3. **Writes / refines skills** — for repeatable things it saw.  *(auto)*
4. **Proposes** automations (cron jobs, digests, commands).     *(review)*

Safe, reversible changes (memory, skills) apply automatically. The
unattended routine runs **without** shell / subagent tools by design.
Adjust auto-approval with `birkin permission --add cron` (or
`/permission`); `memory` and `skill` are auto-approved by default.

A **token budget governor** (`birkin budget`) sums `estTokens` from the run
ledger over a daily / monthly window and refuses over-budget turns with a
clear message — no silent spend.

---

## 🛰️ Gateway & 📊 Dashboard

`birkin gateway` runs the agent as a persistent service. One shared memory
vault and skill catalog back every channel, so birkin remembers you
everywhere:

- **HTTP** (on by default): `POST /message {"session","text"} → {"reply"}`,
  plus `GET /health`. Bound to localhost.
- **Telegram** (optional): `birkin setup` walks you through it, or set
  `channels.telegram` in `config.json`. Pure stdlib long-polling.

`birkin web` serves a local **monitoring** dashboard (not a chat): live
status, scheduled/running jobs, recent runs, pending approvals
(approve/reject with risk tier badges), and the skill catalog. Localhost +
per-session token + Host check.

---

## ⚙️ Configuration

All state lives under `~/.birkin` (override with `BIRKIN_HOME`):

```
~/.birkin/
├── config.json     # provider, model, vault, Morpheus hour, permissions…
├── vault/          # Obsidian semantic memory (markdown notes)
├── skills/         # user- and agent-authored skills
├── sessions/       # saved conversations  (Morpheus input)
│   └── repl_history.txt           # persistent ↑/↓ command history
├── runs/           # per-turn + per-Morpheus run summaries (dashboard)
├── ledger.jsonl    # append-only one-line audit log
├── pending/        # proposed actions awaiting approval
├── cron.json       # registered daily jobs
└── status.json     # daemon heartbeat / next-run info
```

`config.json` — the keys you'll actually touch:

```json
{
  "provider": "anthropic",
  "model": "claude-sonnet-4-6",
  "subagent_model": "claude-haiku-4-5-20251001",
  "base_url": "",
  "vault_path": "",
  "morpheus_hour": 4,
  "auto_approve": ["memory", "skill"],
  "budget_tokens_daily": 0,
  "budget_tokens_monthly": 0,
  "evidence_required": false,
  "gateway_port": 8788,
  "web_port": 8787,
  "channels": {
    "http": {"enabled": true},
    "telegram": {"enabled": false, "token": ""}
  }
}
```

API keys are read from the environment first; CLI-agent providers need
none. A key written to `config.json` is stored `chmod 600`.

---

## 🛠️ Where birkin sits today

- **199 → 265 tests** offline, no API key, with `pytest-cov` enforcing
  **≥ 75 %** coverage. Coverage today: **76.06 %**.
- **48 bundled skills**, all clean against `birkin skills validate`.
- All hardening phases H2 – H7 complete (live-LLM harness, reliability
  control plane, verified learning, Memory OS, skill integrity, full
  line editor with multi-line input + Shift/Ctrl/Alt+Enter via the Kitty
  Keyboard Protocol).
- Full sourced comparison vs hermes-agent and openclaw:
  [`docs/COMPARISON.md`](./docs/COMPARISON.md).

Roadmap: [`docs/HARDENING-PLAN.md`](./docs/HARDENING-PLAN.md). Per-decision
rationale: [`docs/DECISIONS.md`](./docs/DECISIONS.md). Live status:
[`docs/STATUS.md`](./docs/STATUS.md).

---

## 📄 License

Dual: the **birkin Python package** (`birkin/`, the runtime code) is
**Proprietary — All Rights Reserved** (© 2026 ashmoonori). Source is
visible for inspection; no use, copy, modify, distribute, or commercial
right is granted without written permission. The **bundled skill catalog**
(`skills/`) is **MIT-licensed** — the catalog is styled after, and in some
cases ported from, the open-source catalogs of NousResearch/hermes-agent
and openclaw; the upstream MIT terms and any attribution requirements are
preserved. Skills mirrored at runtime via `birkin skills sync` keep their
upstream licenses. See [`LICENSE`](./LICENSE) and [`NOTICE`](./NOTICE).
