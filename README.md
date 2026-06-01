<div align="center">

```
 ██████╗ ██╗██████╗ ██╗  ██╗██╗███╗   ██╗
 ██╔══██╗██║██╔══██╗██║ ██╔╝██║████╗  ██║
 ██████╔╝██║██████╔╝█████╔╝ ██║██╔██╗ ██║
 ██╔══██╗██║██╔══██╗██╔═██╗ ██║██║╚██╗██║
 ██████╔╝██║██║  ██║██║  ██╗██║██║ ╚████║
 ╚═════╝ ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝
```

### Free. Fast. Self-improving by night — audited by you.

A lightweight CLI + Telegram agent that runs **free on your Claude
subscription**, replies in **~3s** from a warm persistent session, **interviews
you to clarity** before tackling vague work (**neurosis**), **auto-saves every
conversation** and turns it into memory overnight (**Morpheus**), connects to
your **company tools over MCP**, and keeps **you the auditor** — all in a
**zero-dependency** Python core.

🌐 **Language**: English · [한국어](./README.ko.md)

![python](https://img.shields.io/badge/python-3.10%2B-3776ab)
![runtime deps](https://img.shields.io/badge/runtime%20deps-0-2ea44f)
![tests](https://img.shields.io/badge/tests-432%20passing-2ea44f)
![skills](https://img.shields.io/badge/bundled%20skills-50-blue)
![platform](https://img.shields.io/badge/platform-macOS%20·%20Linux%20·%20Windows-lightgrey)
![package](https://img.shields.io/badge/package-Proprietary-orange)
![bundled skills](https://img.shields.io/badge/bundled%20skills-MIT-green)

</div>

---

birkin is a personal/company agent you can run **all day for free** on a Claude
Pro/Max subscription — no API key, no per-token bill. It chats in your terminal
and over Telegram from **one shared memory + skills + persona**, and it is built
around a simple promise: **be genuinely useful without surprising you.**

- **Free + fast.** The gateway runs on **Claude Code itself** as a *warm,
  persistent* process per conversation (stream-json). The cold start is paid
  once; subsequent replies are ~model-time (**~3s**), billed to your Claude
  subscription — not a paid API key. See [`docs/DECISIONS.md`](./docs/DECISIONS.md) ADR-026.
- **Clarity before action (neurosis).** For a vague or complex request, birkin
  doesn't guess — it runs a **Socratic deep-interview** with mathematical
  ambiguity scoring, one question at a time, until the idea is crystal clear,
  then writes a spec and acts only after you approve.
- **Self-improving, with receipts (Morpheus).** Every turn is auto-saved; each
  night Morpheus reads the day, updates an Obsidian memory vault, drafts skills,
  and **queues anything consequential** for your morning review.
- **Company-ready.** Inherits Claude Code's **MCP** servers (Notion, Drive,
  Gmail, internal tools) natively, with company-grade security hardening.

Inspired by [hermes-agent](https://github.com/NousResearch/hermes-agent) and
[openclaw](https://github.com/openclaw/openclaw); the deep-interview is ported
from [gajae-code](https://github.com/Yeachan-Heo/gajae-code). Positioned
deliberately *not* on breadth but on **the depth of the trust + clarity
story** — see [`docs/COMPARISON.md`](./docs/COMPARISON.md).

---

## 🎯 Design intent

birkin is deliberately **smaller and more careful** than the inspirations.

1. **Free by default.** The recommended backend is the **Claude subscription**
   via the `claude` CLI — no API key, no paid `extra_usage`. (Direct-API OAuth
   is *parked*, not default: Anthropic meters third-party OAuth-app use as paid
   credits — see ADR-026.)
2. **Fast by default.** The gateway keeps **one warm `claude` process per
   conversation** (stream-json), so warm replies are model-time, not a fresh
   cold start per message.
3. **Stdlib-only runtime.** `pyproject.toml` `dependencies = []`. Install
   anywhere — no version drift. (Dev tooling like `pytest` is opt-in.)
4. **Compile over retrieve.** Memory is a real Obsidian vault of markdown notes
   with `[[wikilinks]]`, frontmatter, **polarity**, **version** (optimistic
   lock), and TTL — not an opaque embedding store. Edit it by hand.
5. **Approval-first.** Memory + skill writes auto-apply (reversible local
   files); cron and shell are queued, risk-tiered. The unattended Morpheus run
   is sandboxed (no shell).
6. **CLI first, dashboard second.** A real terminal line editor (inline `/cmd`
   dropdown, word-wise editing, multi-line, history). The web UI is *monitoring*.

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

Requires **Python 3.10+**. The first run launches an onboarding wizard
(arrow-key navigation).

### Pick a backend

| Backend | How | Cost |
|---|---|---|
| **Claude Code** (`claude`) — *recommended* | be logged into `claude`; pick it in `birkin model` | **free** — your Claude subscription, no API key |
| **Anthropic API** | `export ANTHROPIC_API_KEY=sk-ant-…` | paid (per token) |
| **OpenAI-compatible** | provider `openai` + `base_url` (works with **Ollama**) | paid\* |
| **Codex** (`codex`) | pick it in `birkin model` | uses its own CLI login |

\* Ollama accepts any key. The **gateway** uses the Claude (claude-cli) path and
runs it warm + persistent for speed.

---

## 🗺️ Architecture

```
        terminal (REPL)                         Telegram / HTTP
              │                                       │
              ▼                                       ▼
   ┌────────────────────────┐          ┌──────────────────────────────────┐
   │ repl.py + inline_      │          │ gateway/core.py                  │
   │ complete.py            │          │  · /help /new /restart /hard_    │
   │  · /cmd dropdown       │          │    restart /models /neurosis     │
   │  · word-wise editing   │          │  · per-conversation WARM claude  │
   │  · multi-line, history │          │    (claude_session.py, stream-   │
   └───────────┬────────────┘          │    json) — free + ~3s            │
               │                       └───────────────┬──────────────────┘
               │   one shared memory · skills · persona │
               └───────────────┬───────────────────────┘
                               ▼
        ┌──────────────────────────────────────────────────────────────┐
        │   the agent  (Claude Code, or birkin's own loop on API keys)  │
        │   tools: files · shell · web · subagent · memory_* · skills   │
        │   + inherits Claude Code's MCP servers (company tools)        │
        │   + birkin-as-MCP-server (mcp_server.py): memory/skills/      │
        │     propose tools, so the free claude path stays structured   │
        └───────────────┬───────────────────────────────┬──────────────┘
                         ▼                               ▼
              ~/.birkin/vault/*.md                ~/.birkin/sessions/
              (Obsidian memory:                   auto__*.json
               polarity · version · TTL)          (every turn, auto-saved)
                         ▲                               │
                         │                               ▼
        ┌────────────────┴───────────────────────────────────────────┐
        │  Morpheus (morpheus.py) — nightly 04:00, FREE + SANDBOXED   │
        │   reads last 24h of auto-saved turns ─▶ writes memory/skills │
        │   (via birkin MCP) ─▶ proposes cron/shell (approval-gated)  │
        └──────────────────────────┬──────────────────────────────────┘
                                   ▼
                    approvals.py + risk.py  ─▶  `birkin review`
        (memory/skill = auto · cron/shell = queued; shell-cron can't
         launder past the shell gate)

   neurosis (deep interview): a vague request ─▶ Socratic Q&A with
   ambiguity gating ─▶ spec (~/.birkin/specs/) ─▶ act only after approval
```

---

## 🤔 Why birkin, vs. Claude.ai or the API?

birkin doesn't replace Claude — it *wraps* the `claude` CLI and adds persistence,
structure, and overnight learning. For one-off chats, Claude.ai is fine. For an
agent that knows your context by Wednesday, birkin is the wrapper.

| | Claude.ai / API | birkin |
|---|---|---|
| Cost | Subscription, or per-token API | **Subscription only — no API bill** |
| Memory | Per-session | Persists across sessions; searchable Obsidian vault |
| Telegram | — | Same session, memory & persona as the terminal |
| Ambiguity | Guesses, then proceeds | **neurosis** asks until clear, then writes a spec |
| Self-improvement | — | **Morpheus** updates memory/skills nightly |
| Audit trail | — | Every turn logged; `birkin trace <id>` replay |
| Your files / MCP | Manual paste | Native: Notion, Drive, Gmail, custom servers |
| Security model | Managed by Anthropic | You hold the gates: redaction + approval queues |

---

## 🎮 Quick start

### Run it free + fast (gateway)

```bash
$ birkin model          # pick "claude" (Claude Code) — free, no API key
$ birkin gateway        # warm persistent service: HTTP + (optional) Telegram
                        # warm replies ~3s, billed to your Claude subscription
```

In any chat (terminal or Telegram), type `/` to see the commands. Gateway chat
commands:

| Command | What |
|---|---|
| `/new` (`/reset`) | fresh conversation |
| `/restart` (`/restart-gateway`) | **soft restart** — reload config/persona/memory, no process kill |
| `/hard_restart` | **hard restart** — re-exec the gateway (picks up code changes), no restart loop |
| `/models [name]` | list or **select the gateway model** — auto hard-restarts to apply |
| `/neurosis [--quick\|--standard\|--deep] <idea>` | start/resume a **deep interview** |

### Let it interview you to clarity (neurosis)

For a vague/complex request, birkin proactively says *"진행 전에 모호한 부분과
핵심 결정사항을 다시 한번 확인하겠습니다"* and asks one question at a time until
ambiguity is low — then writes a spec and acts only after you approve.

```bash
you > /neurosis 회사 인스타 캠페인 새로 기획해줘
birkin > Round 0 | 구성요소 확인 …            # topology → targeted questions → spec
```

`birkin neurosis "<idea>"` seeds one from the CLI. Auto-trigger is on by default
(`neurosis_auto`); set it false for explicit-only.

### Chat that remembers — automatically

Every turn is auto-saved to `~/.birkin/sessions/` and turned into memory by
Morpheus overnight. You can also persist a fact on the spot:

```bash
you > /remember I prefer concise replies, no preamble
birkin > Noted as [[Profile - reply-style]].
```

### Morpheus — self-improve overnight, review in the morning

```bash
$ birkin daemon --install   # register the OS task (cron / launchd / schtasks)
$ birkin morpheus --dry-run # preview tonight's run, no spending
$ birkin review             # next morning: approve / reject, one by one
$ birkin trace <run-id>     # audit replay of any past turn
```

Morpheus runs **free** (sandboxed Claude + birkin's MCP tools) and **without
shell** — memory/skills auto-apply; cron/shell are queued.

### Connect company tools (MCP)

```bash
$ birkin mcp                # list MCP servers the gateway inherits (Notion, …)
$ birkin mcp add <name> …   # passes through to `claude mcp`
```

The gateway inherits Claude Code's MCP servers natively. Set
`gateway_allowed_tools` to let the unattended gateway call specific company
tools without a prompt.

---

## 📟 Command cheat sheet

```bash
birkin                              # start chatting (first run → onboarding)
birkin gateway                      # run as a warm, free service (HTTP + Telegram)
birkin neurosis "<idea>"            # seed a deep-interview (drive it with /neurosis)
birkin model                        # pick a model (Claude Code = free)
birkin mcp [list|add|remove|…]      # manage MCP servers (company tools)
birkin mcp-serve                    # run birkin as an MCP server (used internally)
birkin morpheus [--dry-run]         # run the nightly self-improvement now
birkin daemon  [--install]          # Morpheus + cron scheduler
birkin review                       # approve / reject proposed actions
birkin runs / trace <id> / budget   # audit log · replay · token budget
birkin skills [validate|sync]       # list / lint / mirror skills
birkin permission [--access …]      # auto-approve categories · CLI access level
birkin web                          # monitoring dashboard
```

### In-chat slash commands (REPL)

Type `/help` for the full list. Line editor: **Ctrl+←/→** word motion, **Ctrl-W**
delete word, **Ctrl-U/Ctrl-K** clear to start/end, **↑/↓** history, **Shift+Enter**
newline, inline `/`-dropdown.

| Group | Commands |
|---|---|
| **Conversation** | `/new` · `/retry` · `/undo` · `/compact` · `/clear` |
| **Clarify** | `/neurosis [name]` (deep interview) |
| **Model** | `/model` · `/models [name]` · `/provider` · `/temp` |
| **Skills** | `/skills` · `/skill <name>` · `/reload` · `/learn` |
| **Memory** | `/memory <query>` · `/remember <text>` · `/vault` · `/soul` · `/personality` |
| **Tools** | `/mcp` · `/tools` |
| **Autonomy** | `/morpheus` · `/review` · `/cron` · `/permission` |
| **Session** | `/save` · `/load` · `/sessions` |
| **System** | `/system` · `/config` · `/update` · `/help` · `/quit` |

---

## 🧠 Memory & 🗣️ Persona

**Memory** lives at `~/.birkin/vault` — sourced markdown notes with `type`,
`polarity` (positive / known-failure), `version` (optimistic lock), TTL, and
`[[wikilinks]]`. Tools: `memory_search`, `memory_get_note`, `memory_write_note`,
`memory_link`. Set `evidence_required: true` to refuse sourceless notes.

**Persona** is `~/.birkin/SOUL.md` — a warm, editable voice injected into every
surface (read fresh each turn in the REPL; on session start in the gateway).
`/personality warm|concise|mentor|direct` swaps presets; `/soul` shows/edits it.

---

## 🧩 Skills

A skill is a directory with a `SKILL.md` (frontmatter + markdown), compatible
with the agentskills.io / hermes standard. **50 bundled** under
[`skills/`](./skills) (research, software, writing, data, devops, marketing,
planning/**neurosis**, automation/**morpheus**, …), plus your own under
`~/.birkin/skills/` (which shadow
bundled ones). `load_skill` pulls full text on demand; `create_skill` /
`improve_skill` route through the approval gate; `birkin skills validate` lints
frontmatter + `py_compile`s bundled scripts; skills **hot-reload** on edit.

---

## 🔒 Security (company-grade)

birkin is built to run unattended in a company without surprising you — see
[`docs/DECISIONS.md`](./docs/DECISIONS.md) ADR-029:

- **cron→shell gate.** An auto-approved `cron` can't launder a `shell` payload
  past the shell gate — it's queued for review unless `shell` is also approved.
- **Gateway is never `--dangerously-skip-permissions`.** A reachable chat
  message can't reach a fully-permissioned process; `cli_access:full` is forced
  to `workspace` for the gateway.
- **Telegram access control + trust-gated memory.** `allowed_chat_ids` gates who
  may drive the bot; an *open* bot's strangers are **not** auto-saved or
  memorized (anti memory-poisoning).
- **Secret redaction.** Transcripts are scrubbed (Anthropic/OpenAI/Google/GitHub/
  Slack/AWS keys, tokens, Bearer, PEM) before they hit disk or memory.
- **At rest.** State + transcripts are written atomically, `0o600`. Prefer
  `TELEGRAM_BOT_TOKEN` env over a plaintext config token.

---

## ⚙️ Configuration

All state lives under `~/.birkin` (override with `BIRKIN_HOME`):

```
~/.birkin/
├── config.json     # provider, model, gateway, autosave, neurosis, permissions…
├── vault/          # Obsidian semantic memory (markdown notes)
├── skills/         # user- and agent-authored skills
├── sessions/       # auto-saved transcripts (auto__*.json) — Morpheus input
├── specs/          # neurosis deep-interview specs
├── neurosis/       # interview state (resumable)
├── runs/           # per-turn + per-Morpheus run summaries
├── ledger.jsonl    # append-only audit log
├── pending/        # proposed actions awaiting approval
└── status.json     # daemon heartbeat
```

Keys you'll actually touch:

```json
{
  "provider": "claude-cli",
  "model": "opus",
  "gateway_model": "sonnet",
  "gateway_persistent": true,
  "gateway_allowed_tools": [],
  "autosave_transcripts": true,
  "neurosis_auto": true,
  "neurosis_threshold": null,
  "morpheus_hour": 4,
  "auto_approve": ["memory", "skill"],
  "channels": {
    "http": {"enabled": true},
    "telegram": {"enabled": false, "token": "", "allowed_chat_ids": []}
  }
}
```

API keys are read from the environment first; the Claude Code backend needs
none. A key in `config.json` is stored `chmod 600`.

---

## 🛠️ Where birkin sits today

- **432 tests** passing offline (no API key, `pytest`), **50 bundled skills**,
  **0 runtime dependencies**, Python 3.10+.
- Free + fast gateway (warm persistent Claude, ~3s), neurosis deep-interview,
  auto-save → memory, company MCP, company-grade security hardening.
- Rationale per decision: [`docs/DECISIONS.md`](./docs/DECISIONS.md) (ADRs
  001–033). Live status: [`docs/STATUS.md`](./docs/STATUS.md). Comparison:
  [`docs/COMPARISON.md`](./docs/COMPARISON.md).

---

## 🙌 Contributing

Skills are **MIT-licensed** and the easiest place to contribute: a skill is just a
directory with a `SKILL.md` (frontmatter + markdown) — see any folder under
[`skills/`](./skills) for the format, run `birkin skills validate` to lint it, and
open a PR with a new skill or an improvement. Bug reports and feature requests are
welcome as issues.

If birkin saves you money or time, **starring the repo** is the single most
helpful thing you can do — it helps other Claude subscribers find it. ⭐

---

## 📄 License

Dual: the **birkin Python package** (`birkin/`) is **Proprietary — All Rights
Reserved** (© 2026 ashmoonori). Source is visible for inspection; no use, copy,
modify, distribute, or commercial right is granted without written permission.
The **bundled skill catalog** (`skills/`) is **MIT-licensed** — styled after,
and in some cases ported from, the open-source catalogs of NousResearch/
hermes-agent and openclaw; the deep-interview skill is adapted from
Yeachan-Heo/gajae-code. Upstream MIT terms and attribution are preserved. See
[`LICENSE`](./LICENSE) and [`NOTICE`](./NOTICE).
